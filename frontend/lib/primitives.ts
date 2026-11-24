import type { ISeriesPrimitivePaneRenderer, ISeriesPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";

export type Box = { t1: Time; t2: Time | null; low: number; high: number; fill: string; stroke?: string; label?: string };
export type ProfileBin = { low: number; high: number; volume: number };
export type Profile = { bins: ProfileBin[]; poc: number; vah: number; val: number };

type Param = SeriesAttachedParameter<Time>;

abstract class Base implements ISeriesPrimitive<Time> {
  protected p?: Param;
  attached(p: Param) { this.p = p; }
  detached() { this.p = undefined; }
  updateAllViews() {}
  abstract draw(target: CanvasRenderingTarget2D): void;
  paneViews(): ISeriesPrimitivePaneView[] {
    const self = this;
    return [{ zOrder: () => "bottom", renderer: (): ISeriesPrimitivePaneRenderer => ({ draw: (t) => self.draw(t) }) }];
  }
}

/** Horizontal price zones from a start time to an end time (or the right edge). */
export class BoxesPrimitive extends Base {
  constructor(private boxes: Box[]) { super(); }
  draw(target: CanvasRenderingTarget2D) {
    const p = this.p;
    if (!p) return;
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hx, verticalPixelRatio: vy, mediaSize }) => {
      for (const b of this.boxes) {
        const y1 = p.series.priceToCoordinate(b.high), y2 = p.series.priceToCoordinate(b.low);
        if (y1 === null || y2 === null) continue;
        const xa = p.chart.timeScale().timeToCoordinate(b.t1);
        const xb = b.t2 === null ? mediaSize.width : p.chart.timeScale().timeToCoordinate(b.t2);
        const x1 = Math.max(0, xa ?? 0), x2 = Math.min(mediaSize.width, xb ?? mediaSize.width);
        if (x2 <= x1) continue;
        ctx.fillStyle = b.fill;
        ctx.fillRect(x1 * hx, Math.min(y1, y2) * vy, (x2 - x1) * hx, Math.max(1, Math.abs(y2 - y1)) * vy);
        if (b.stroke) {
          ctx.strokeStyle = b.stroke; ctx.lineWidth = 1;
          ctx.strokeRect(x1 * hx, Math.min(y1, y2) * vy, (x2 - x1) * hx, Math.max(1, Math.abs(y2 - y1)) * vy);
        }
        if (b.label) {
          ctx.fillStyle = b.stroke ?? "#64748b"; ctx.font = `${10 * hx}px sans-serif`;
          ctx.fillText(b.label, (x1 + 3) * hx, (Math.min(y1, y2) + 11) * vy);
        }
      }
    });
  }
}

/** Volume-at-price histogram anchored to the right edge of the pane. */
export class ProfilePrimitive extends Base {
  constructor(private prof: Profile, private maxPx = 150) { super(); }
  draw(target: CanvasRenderingTarget2D) {
    const p = this.p;
    if (!p) return;
    const max = Math.max(...this.prof.bins.map((b) => b.volume), 1);
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hx, verticalPixelRatio: vy, mediaSize }) => {
      for (const b of this.prof.bins) {
        const y1 = p.series.priceToCoordinate(b.high), y2 = p.series.priceToCoordinate(b.low);
        if (y1 === null || y2 === null) continue;
        const w = (b.volume / max) * this.maxPx;
        const mid = (b.low + b.high) / 2;
        const inVA = mid >= this.prof.val && mid <= this.prof.vah;
        const isPoc = this.prof.poc >= b.low && this.prof.poc <= b.high;
        ctx.fillStyle = isPoc ? "#f59e0bcc" : inVA ? "#6366f166" : "#94a3b844";
        ctx.fillRect((mediaSize.width - w) * hx, Math.min(y1, y2) * vy, w * hx, Math.max(1, Math.abs(y2 - y1) - 1) * vy);
      }
    });
  }
}
