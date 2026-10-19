"""屏幕元素斑点检测。

两种模式：
1. contour（默认）：Canny 边缘 → 形态学闭运算/膨胀 → 连通域轮廓 → 外接矩形
   → 面积/宽高比/紧致度过滤 → NMS 合并。适合识别图标、按钮、窗口区域等矩形元素。
2. simpleblob：OpenCV SimpleBlobDetector 经典斑点检测（多阈值二值化 + 质心聚类）。

所有输出均为检测图坐标系下的 (x, y, w, h) 矩形，调用方负责换算回屏幕坐标。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import cv2
import numpy as np

Rect = Tuple[float, float, float, float]


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _quantize(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def snap_boxes(boxes: List[Rect], step: float) -> List[Rect]:
    """把框的 x/y/w/h 吸附到 step 像素网格，并去掉完全重复的框。

    同一元素在相邻帧里往往只有 1~2 像素的差别（抗锯齿、压缩、光标边缘），
    吸附后它们输出完全相同的坐标，从源头消除“框在抖”的观感。
    """
    if step <= 0:
        return list(boxes)
    out: List[Rect] = []
    seen = set()
    for (x, y, w, h) in boxes:
        key = (
            _quantize(x, step), _quantize(y, step),
            _quantize(w, step), _quantize(h, step),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append((float(key[0]), float(key[1]), max(step, float(key[2])), max(step, float(key[3]))))
    return out


def nms(boxes: List[Rect], iou_thr: float, limit: int, step: float = 0.0) -> List[Rect]:
    """按“面积降序”做非极大值抑制，并限制返回数量。

    排序键经过网格量化：面积的小幅抖动不会改变顺序，
    因此不会像精确排序那样每帧翻转“保留哪一组”，从源头消除整组框闪变。
    """
    if not boxes:
        return []
    q = step if step > 0 else 1.0
    area_unit = q * q * 64.0

    def order_key(i: int):
        x, y, w, h = boxes[i]
        return (-round((w * h) / area_unit), round(y / q), round(x / q))

    order = sorted(range(len(boxes)), key=order_key)
    keep: List[Rect] = []
    for i in order:
        box = boxes[i]
        if any(iou(box, k) > iou_thr for k in keep):
            continue
        keep.append(box)
        if len(keep) >= limit:
            break
    return keep


def _prepare(gray: "np.ndarray", cfg) -> "np.ndarray":
    """缩放 + 模糊（检测在缩小后的图上做，显著降低 CPU）。"""
    img = gray
    if cfg.downscale < 0.999:
        h, w = img.shape[:2]
        nw = max(8, int(round(w * cfg.downscale)))
        nh = max(8, int(round(h * cfg.downscale)))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    k = int(cfg.blur) | 1
    if k > 1:
        img = cv2.GaussianBlur(img, (k, k), 0)
    return img


def _detect_contours(img: "np.ndarray", cfg, k: float) -> List[Rect]:
    edges = cv2.Canny(img, float(cfg.canny_low), float(cfg.canny_high), apertureSize=3)

    mk = int(cfg.morph_kernel)
    if mk >= 3 and (cfg.morph_iterations > 0 or cfg.dilate_iterations > 0):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
        if cfg.morph_iterations > 0:
            edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=int(cfg.morph_iterations))
        if cfg.dilate_iterations > 0:
            edges = cv2.dilate(edges, kernel, iterations=int(cfg.dilate_iterations))

    found = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = found[0] if len(found) == 2 else found[1]

    min_area = cfg.min_area * k * k
    max_area = cfg.max_area * k * k
    pad = cfg.padding * k
    h, w = img.shape[:2]

    boxes: List[Rect] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw <= 0 or ch <= 0:
            continue
        aspect = cw / float(ch)
        if aspect < cfg.min_aspect or aspect > cfg.max_aspect:
            continue
        extent = area / float(cw * ch)
        if extent < cfg.min_extent:
            continue
        x -= pad
        y -= pad
        cw += pad * 2
        ch += pad * 2
        x = max(0.0, min(float(w - 1), x))
        y = max(0.0, min(float(h - 1), y))
        cw = max(1.0, min(float(w) - x, cw))
        ch = max(1.0, min(float(h) - y, ch))
        boxes.append((float(x), float(y), float(cw), float(ch)))
    return boxes


def _detect_simpleblob(img: "np.ndarray", cfg, k: float) -> List[Rect]:
    params = cv2.SimpleBlobDetector_Params()
    params.filterByArea = True
    params.minArea = max(1.0, cfg.min_area * k * k)
    params.maxArea = max(2.0, cfg.max_area * k * k)
    params.minDistBetweenBlobs = float(cfg.blob_min_dist)
    params.minRepeatability = 1
    params.minThreshold = float(cfg.blob_min_threshold)
    params.maxThreshold = float(cfg.blob_max_threshold)
    params.thresholdStep = float(cfg.blob_step)
    params.filterByColor = True
    params.blobColor = 255 if cfg.blob_bright else 0
    params.filterByCircularity = bool(cfg.filter_circularity)
    params.minCircularity = float(cfg.min_circularity)
    params.filterByConvexity = bool(cfg.filter_convexity)
    params.minConvexity = float(cfg.min_convexity)
    params.filterByInertia = bool(cfg.filter_inertia)
    params.minInertiaRatio = float(cfg.min_inertia)

    detector = cv2.SimpleBlobDetector_create(params)
    keypoints = detector.detect(img)
    pad = cfg.padding * k
    boxes: List[Rect] = []
    for kp in keypoints:
        size = max(2.0, float(kp.size) * 1.25) + pad * 2
        boxes.append((float(kp.pt[0]) - size / 2.0, float(kp.pt[1]) - size / 2.0, size, size))
    return boxes


def detect_blobs(gray: "np.ndarray", cfg, px_per_logical: float) -> List[Rect]:
    """在灰度图上检测界面元素。

    gray:       原始分辨率灰度图（uint8）
    cfg:        DetectCfg
    px_per_logical: 1 个屏幕逻辑像素对应多少检测图像素（= DPI 缩放 × downscale）
    返回:       检测图坐标系下的矩形列表
    """
    if gray is None or gray.size == 0:
        return []
    img = _prepare(gray, cfg)
    if cfg.mode == "simpleblob":
        boxes = _detect_simpleblob(img, cfg, px_per_logical)
    else:
        boxes = _detect_contours(img, cfg, px_per_logical)

    # 把检测图坐标换算成“屏幕逻辑像素”后再量化，保证 snap 的单位对用户一致
    step = float(cfg.snap) * px_per_logical
    boxes = snap_boxes(boxes, max(1.0, round(step)) if cfg.snap > 0 else 0.0)
    boxes = nms(boxes, float(cfg.nms_iou), int(cfg.max_blobs), max(1.0, round(step)) if cfg.snap > 0 else 0.0)
    return _enforce_min_dist(boxes, float(cfg.min_dist) * px_per_logical)


def _enforce_min_dist(boxes: List[Rect], min_dist: float) -> List[Rect]:
    """元素中心最小间距（BlobTrack 的 Delete Nearby）：距离太近时只保留较大的那个。"""
    if min_dist <= 0.0 or not boxes:
        return list(boxes)
    d2 = min_dist * min_dist
    order = sorted(range(len(boxes)),
                   key=lambda i: (boxes[i][2] * boxes[i][3], i), reverse=True)
    kept: List[Rect] = []
    for i in order:
        x, y, w, h = boxes[i]
        cx, cy = x + w / 2.0, y + h / 2.0
        if any((cx - (kx + kw / 2.0)) ** 2 + (cy - (ky + kh / 2.0)) ** 2 < d2
               for (kx, ky, kw, kh) in kept):
            continue
        kept.append(boxes[i])
    return kept
