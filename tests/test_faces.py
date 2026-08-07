"""Tests for the Synology face bounding-box IoU matcher."""

import json

from syno_immich.faces import parse_syno_bbox, compute_iou


class TestParseSynoBbox:
    def test_dict_input(self):
        bbox = {
            "top_left": {"x": 0.1, "y": 0.2},
            "bottom_right": {"x": 0.5, "y": 0.8},
        }
        result = parse_syno_bbox(bbox)
        assert result == (0.1, 0.2, 0.5, 0.8)

    def test_json_string_input(self):
        bbox = json.dumps(
            {
                "top_left": {"x": 0.0, "y": 0.0},
                "bottom_right": {"x": 1.0, "y": 1.0},
            }
        )
        result = parse_syno_bbox(bbox)
        assert result == (0.0, 0.0, 1.0, 1.0)

    def test_missing_keys_defaults_to_zero(self):
        result = parse_syno_bbox({})
        assert result == (0, 0, 0, 0)

    def test_partial_data(self):
        bbox = {"top_left": {"x": 0.3}, "bottom_right": {}}
        result = parse_syno_bbox(bbox)
        assert result == (0.3, 0, 0, 0)


class TestComputeIoU:
    def _imm_face(self, x1, y1, x2, y2, w=1000, h=1000):
        return {
            "boundingBoxX1": x1,
            "boundingBoxY1": y1,
            "boundingBoxX2": x2,
            "boundingBoxY2": y2,
            "imageWidth": w,
            "imageHeight": h,
        }

    def test_identical_boxes(self):
        syno = {"top_left": {"x": 0.1, "y": 0.1}, "bottom_right": {"x": 0.5, "y": 0.5}}
        imm = self._imm_face(100, 100, 500, 500, 1000, 1000)
        iou = compute_iou(syno, imm)
        assert abs(iou - 1.0) < 0.001

    def test_no_overlap(self):
        syno = {"top_left": {"x": 0.0, "y": 0.0}, "bottom_right": {"x": 0.1, "y": 0.1}}
        imm = self._imm_face(500, 500, 1000, 1000, 1000, 1000)
        iou = compute_iou(syno, imm)
        assert iou == 0.0

    def test_partial_overlap(self):
        syno = {"top_left": {"x": 0.0, "y": 0.0}, "bottom_right": {"x": 0.5, "y": 0.5}}
        imm = self._imm_face(250, 250, 750, 750, 1000, 1000)
        iou = compute_iou(syno, imm)
        inter = 250 * 250
        union = 500 * 500 + 500 * 500 - inter
        expected = inter / union
        assert abs(iou - expected) < 0.001

    def test_zero_dimensions(self):
        syno = {"top_left": {"x": 0.0, "y": 0.0}, "bottom_right": {"x": 0.5, "y": 0.5}}
        imm = self._imm_face(100, 100, 500, 500, 0, 0)
        iou = compute_iou(syno, imm)
        assert iou == 0.0

    def test_syno_box_larger_than_imm(self):
        syno = {"top_left": {"x": 0.0, "y": 0.0}, "bottom_right": {"x": 1.0, "y": 1.0}}
        imm = self._imm_face(400, 400, 600, 600, 1000, 1000)
        iou = compute_iou(syno, imm)
        inter = 200 * 200
        union = 1000 * 1000
        assert abs(iou - inter / union) < 0.001
