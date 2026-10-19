"""斑点时序跟踪：跨帧 IoU 匹配 + 可选的出现确认。

设计原则（v1.2）：
- **默认不插值、不保留消失的框**。画出来的框严格等于当前帧的检测结果，
  不再有“缓动/缩放/漂移”这类人为动画，也不会出现“旧框 + 新框叠在一起两种框”。
- 需要消除抖动时，靠 detector 的坐标吸附（snap）+ 稳定排序在源头解决，
  而不是用插值把结果往后拖。
- smoothing > 0 时才启用指数平滑（作为可选的老行为保留）。
- confirm_frames > 1 时，元素必须连续出现 N 帧才会被绘制，用于滤掉一闪而过的噪声。

每个跟踪结果都带上它在“本帧检测结果列表”中的源索引（src_index），
覆盖层据此把填充贴图精确对应到框上 —— 保证只有真正画出来的框才会被填充。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from aura.detector import iou

Rect = Tuple[float, float, float, float]
# (box, hits, src_index)  hits = 该元素已连续/累计出现的帧数
TrackedBox = Tuple[Rect, int, int]


class BlobTracker:
    def __init__(self, smoothing: float = 0.0, max_missing: int = 0,
                 match_iou: float = 0.15, confirm_frames: int = 1):
        self.smoothing = smoothing
        self.max_missing = max_missing
        self.match_iou = match_iou
        self.confirm_frames = confirm_frames
        self._slots: List[list] = []    # [box, missing, hits, src_index]
        self._pending: List[list] = []  # [box, hits, src_index]  尚未确认的新候选

    def reset(self) -> None:
        self._slots = []
        self._pending = []

    def update(self, boxes: Sequence[Sequence[float]]) -> List[TrackedBox]:
        incoming = [(float(b[0]), float(b[1]), float(b[2]), float(b[3])) for b in boxes]
        used = set()
        fresh: List[list] = []

        # 1) 已确认的槽位：按 IoU 与当前帧匹配
        for box, missing, hits, _src in self._slots:
            best, best_iou = -1, self.match_iou
            for j, cand in enumerate(incoming):
                if j in used:
                    continue
                value = iou(box, cand)
                if value > best_iou:
                    best_iou, best = value, j
            if best >= 0:
                used.add(best)
                hits += 1
                target = incoming[best]
                if self.smoothing > 0.0:
                    a = 1.0 - self.smoothing
                    moved = tuple(box[i] + (target[i] - box[i]) * a for i in range(4))
                else:
                    moved = target  # 严格跟随检测结果，不做缓动
                fresh.append([moved, 0, hits, best])
            elif self.max_missing > 0 and missing + 1 < self.max_missing:
                # 可选：短暂消失时保留 1~2 帧（会造成“两种框叠加”，默认关闭）
                # 保留的框没有本帧来源，src_index = -1（不会有任何填充）
                fresh.append([box, missing + 1, hits, -1])
            # 否则立即丢弃：屏幕上出现过的东西才画，消失了就该消失

        # 2) 本帧新出现的候选：需连续出现 confirm_frames 帧才绘制
        rest = [(j, c) for j, c in enumerate(incoming) if j not in used]
        next_pending: List[list] = []
        for j, cand in rest:
            hits = 1
            for p in self._pending:
                if iou(p[0], cand) >= self.match_iou:
                    hits = p[1] + 1
                    break
            if hits >= max(1, self.confirm_frames):
                fresh.append([cand, 0, hits, j])
            else:
                next_pending.append([cand, hits, j])
        # 已经与上面对上的候选会被替换成最新框，未再出现的候选自然淘汰
        self._pending = next_pending
        self._slots = fresh
        return [(slot[0], slot[2], slot[3]) for slot in self._slots]
