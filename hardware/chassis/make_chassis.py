"""아크릴 2층 섀시 도면 생성 — DXF(레이저 재단용, mm)와 SVG 미리보기.

좌표: 판의 왼쪽 앞 모서리가 원점, x는 오른쪽, y는 뒤쪽(mm).
치수는 박스 섀시에서 실측한 값(2026-10-07~08). 바꾸려면 아래 상수만 고친다.
"""
import math
from pathlib import Path

OUT = Path(__file__).parent

# --- 판 ---
W, H = 200.0, 250.0          # 좌우 x 앞뒤
CORNER_R = 5.0
M3 = 3.4                     # M3 나사 구멍
CORNER_HOLES = [(6, 6), (W - 6, 6), (6, H - 6), (W - 6, H - 6)]   # 층간 기둥

# --- 아래층: 모터 브래킷 (바닥판을 판 위에 얹고 모터는 판 아래) ---
AXLES_Y = (50.0, 200.0)      # 앞뒤 바퀴 축선 (앞 가장자리에서)
BR_X = (7.0, 32.0)           # 세로판 안쪽면(=판 가장자리)에서 구멍 중심
BR_DY = 15.0                 # 축선에서 앞뒤로 (구멍 간격 30mm)
WIRE_HOLES = [(47, 85), (W - 47, 85), (47, H - 85), (W - 47, H - 85)]
WIRE_D = 10.0

# --- 위층 ---
JETSON = (103.0, 90.0)       # 플라스틱 틀 실측 (x, y)
JETSON_Y0 = 40.0             # 틀 앞변
STOP_GAP = 1.5               # 틀과 멈춤 기둥 사이 여유
STOP_R = 3.0                 # 멈춤 기둥(M3 스페이서) 반지름
PBANK = (61.0, 72.0)         # Baseus AC22 10000mAh (x, y)
PBANK_Y0 = 150.0
CAM_SLOT_Y = 15.0            # 카메라 판 끼우는 홈 중심

# --- 카메라 판 (세워서 위층 홈에 끼우고 접착) ---
CAM_W, CAM_H, TAB_H = 50.0, 47.0, 3.0   # 탭 포함 50 x 50 (재단 최소 50mm)
TABS = [(9.0, 17.0), (33.0, 41.0)]
CAM_EDGE_Z = 12.0            # 카메라 기판 커넥터 쪽 가장자리 높이(판 위에서)
CAM_HOLE_DX, CAM_HOLE_DZ, CAM_HOLE_FROM_EDGE = 21.0, 14.0, 9.0
M2 = 2.4


class Sheet:
    """같은 도형을 DXF(y 위로)와 SVG(y 아래로) 두 곳에 그린다."""

    def __init__(self):
        self.dxf, self.svg = [], []

    # DXF 기본 요소 — (X, Y)는 이미 DXF 좌표
    def _line(self, a, b, layer):
        self.dxf.append(f"0\nLINE\n8\n{layer}\n10\n{a[0]:.3f}\n20\n{a[1]:.3f}\n30\n0\n"
                        f"11\n{b[0]:.3f}\n21\n{b[1]:.3f}\n31\n0\n")

    def _arc(self, c, r, a0, a1, layer):
        self.dxf.append(f"0\nARC\n8\n{layer}\n10\n{c[0]:.3f}\n20\n{c[1]:.3f}\n30\n0\n"
                        f"40\n{r:.3f}\n50\n{a0:.3f}\n51\n{a1:.3f}\n")

    def _circle(self, c, r, layer):
        self.dxf.append(f"0\nCIRCLE\n8\n{layer}\n10\n{c[0]:.3f}\n20\n{c[1]:.3f}\n30\n0\n40\n{r:.3f}\n")

    def poly(self, pts, layer="CUT"):
        for a, b in zip(pts, pts[1:] + pts[:1]):
            self._line(a, b, layer)

    def round_rect(self, x0, y0, w, h, r, layer="CUT"):
        x1, y1 = x0 + w, y0 + h
        self._line((x0 + r, y0), (x1 - r, y0), layer)
        self._line((x1, y0 + r), (x1, y1 - r), layer)
        self._line((x1 - r, y1), (x0 + r, y1), layer)
        self._line((x0, y1 - r), (x0, y0 + r), layer)
        self._arc((x1 - r, y0 + r), r, 270, 360, layer)
        self._arc((x1 - r, y1 - r), r, 0, 90, layer)
        self._arc((x0 + r, y1 - r), r, 90, 180, layer)
        self._arc((x0 + r, y0 + r), r, 180, 270, layer)

    def slot(self, cx, cy, w, h, layer="CUT"):
        """양 끝이 둥근 긴 구멍 (DXF 좌표 중심, 전체 폭 w x 높이 h)."""
        if w >= h:
            r, d = h / 2, w / 2 - h / 2
            self._line((cx - d, cy - r), (cx + d, cy - r), layer)
            self._line((cx + d, cy + r), (cx - d, cy + r), layer)
            self._arc((cx + d, cy), r, 270, 90, layer)
            self._arc((cx - d, cy), r, 90, 270, layer)
        else:
            r, d = w / 2, h / 2 - w / 2
            self._line((cx + r, cy - d), (cx + r, cy + d), layer)
            self._line((cx - r, cy + d), (cx - r, cy - d), layer)
            self._arc((cx, cy + d), r, 0, 180, layer)
            self._arc((cx, cy - d), r, 180, 360, layer)

    def circle(self, cx, cy, d, layer="CUT"):
        self._circle((cx, cy), d / 2, layer)

    def write_dxf(self, path):
        body = "".join(self.dxf)
        path.write_text("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n"
                        "0\nSECTION\n2\nENTITIES\n" + body + "0\nENDSEC\n0\nEOF\n", encoding="ascii")


def plate(sheet, svg, ox, oy, title, cut, ref):
    """판 하나. cut(add)는 판 좌표(x, y=앞에서)로 구멍을 넣고, ref는 SVG 참고 외곽만 그린다."""
    to = lambda x, y: (ox + x, oy + (H - y))          # 판 좌표 → DXF
    sheet.round_rect(ox, oy, W, H, CORNER_R)
    S = 1.6                                             # SVG 배율 px/mm
    sx, sy = 20 + ox * S, 60
    g = [f'<g transform="translate({sx},{sy})">',
         f'<text x="0" y="-14" class="t">{title}</text>',
         f'<rect x="0" y="0" width="{W*S}" height="{H*S}" rx="{CORNER_R*S}" class="plate"/>',
         f'<text x="{W*S/2}" y="-2" class="s" text-anchor="middle">앞</text>']

    def add_circle(x, y, d, cls="hole"):
        sheet.circle(*to(x, y), d)
        g.append(f'<circle cx="{x*S}" cy="{y*S}" r="{d/2*S}" class="{cls}"/>')

    def add_slot(x, y, w, h):          # w: x방향, h: y방향
        sheet.slot(*to(x, y), w, h)
        g.append(f'<rect x="{(x-w/2)*S}" y="{(y-h/2)*S}" width="{w*S}" height="{h*S}" '
                 f'rx="{min(w,h)/2*S}" class="hole"/>')

    def add_rect(x, y, w, h):          # 각진 구멍 (카메라 판 탭)
        x0, y0 = x - w / 2, y - h / 2
        sheet.poly([to(x0, y0), to(x0 + w, y0), to(x0 + w, y0 + h), to(x0, y0 + h)])
        g.append(f'<rect x="{x0*S}" y="{y0*S}" width="{w*S}" height="{h*S}" class="hole"/>')

    def ref_rect(x0, y0, w, h, label, cls="ref"):
        g.append(f'<rect x="{x0*S}" y="{y0*S}" width="{w*S}" height="{h*S}" class="{cls}"/>'
                 f'<text x="{(x0+w/2)*S}" y="{(y0+h/2)*S+4}" class="s" text-anchor="middle">{label}</text>')

    for x, y in CORNER_HOLES:
        add_circle(x, y, M3)
    cut(add_circle, add_slot, add_rect)
    ref(ref_rect)
    g.append("</g>")
    svg.extend(g)


def lower_cut(add_circle, add_slot, add_rect):
    for ay in AXLES_Y:
        for bx in BR_X:
            for dy in (-BR_DY, BR_DY):
                add_circle(bx, ay + dy, M3)
                add_circle(W - bx, ay + dy, M3)
    for x, y in WIRE_HOLES:
        add_circle(x, y, WIRE_D)


def lower_ref(ref_rect):
    for ay in AXLES_Y:                       # 모터(판 아래)·브래킷 바닥판(판 위)
        ref_rect(0, ay - 12.5, 62, 25, "", "under")
        ref_rect(W - 62, ay - 12.5, 62, 25, "", "under")
        ref_rect(-3, ay - 20, 40, 40, "", "ref")
        ref_rect(W - 37, ay - 20, 40, 40, "", "ref")
    ref_rect(4, 90, 50, 50, "L 드라이버")
    ref_rect(W - 54, 90, 50, 50, "R 드라이버")
    ref_rect(W / 2 - 22.5, 92, 45, 65, "배터리")
    ref_rect(W / 2 - 14, 8, 28, 55, "ESP32")
    ref_rect(W / 2 - 42.5, 212, 85, 30, "터미널블럭")


def upper_cut(add_circle, add_slot, add_rect):
    jx0 = W / 2 - JETSON[0] / 2
    jx1, jy1 = jx0 + JETSON[0], JETSON_Y0 + JETSON[1]
    off = STOP_GAP + STOP_R
    for y in (JETSON_Y0 + 10, jy1 - 10):     # 좌우 멈춤 기둥
        add_circle(jx0 - off, y, M3)
        add_circle(jx1 + off, y, M3)
    add_circle(W / 2, JETSON_Y0 - off, M3)   # 앞 멈춤 기둥 (뒤는 포트라 비움)
    add_slot(W / 2, 140, 30, 12)             # ESP32 USB 선 통과
    px0 = W / 2 - PBANK[0] / 2
    for x in (px0 - 5.5, px0 + PBANK[0] + 5.5):   # 보조배터리 고정 끈
        add_slot(x, PBANK_Y0 + PBANK[1] / 2, 4, 16)
    for t0, t1 in TABS:                      # 카메라 판 탭 홈
        add_rect(W / 2 - CAM_W / 2 + (t0 + t1) / 2, CAM_SLOT_Y, (t1 - t0) + 0.4, TAB_H + 0.4)


def upper_ref(ref_rect):
    ref_rect(W / 2 - JETSON[0] / 2, JETSON_Y0, *JETSON, "Jetson (포트 ↓뒤)")
    ref_rect(W / 2 - PBANK[0] / 2, PBANK_Y0, *PBANK, "보조배터리")
    ref_rect(W / 2 - 12.5, CAM_SLOT_Y - 8, 25, 6, "", "under")
    ref_rect(W / 2 - CAM_W / 2, CAM_SLOT_Y - 1.5, CAM_W, 3, "", "ref")


def camera_plate(sheet, svg, ox, oy):
    """세워 쓰는 카메라 판. 아래 탭이 위층 홈에 들어간다. z=0이 위층 윗면."""
    to = lambda x, z: (ox + x, oy + TAB_H + z)
    (a0, a1), (b0, b1) = TABS
    outline = [(0, 0), (a0, 0), (a0, -TAB_H), (a1, -TAB_H), (a1, 0), (b0, 0), (b0, -TAB_H),
               (b1, -TAB_H), (b1, 0), (CAM_W, 0), (CAM_W, CAM_H), (0, CAM_H)]
    sheet.poly([to(*p) for p in outline])
    sheet.slot(*to(CAM_W / 2, 7), 20, 4)                       # FPC 통과 창
    zl = CAM_EDGE_Z + CAM_HOLE_FROM_EDGE
    for x in (CAM_W / 2 - CAM_HOLE_DX / 2, CAM_W / 2 + CAM_HOLE_DX / 2):
        sheet.circle(*to(x, zl), M2)
        sheet.slot(*to(x, zl + CAM_HOLE_DZ), M2, 5)            # 실측 오차 흡수용 세로 긴 구멍
    S = 2.6
    sx, sy = 20 + ox * 1.6, 60
    pts = " ".join(f"{x*S},{(CAM_H - z)*S}" for x, z in outline)
    hl = [f'<circle cx="{x*S}" cy="{(CAM_H-zl)*S}" r="{M2/2*S}" class="hole"/>'
          f'<rect x="{(x-M2/2)*S}" y="{(CAM_H-zl-CAM_HOLE_DZ-2.5)*S}" width="{M2*S}" height="{5*S}" rx="{M2/2*S}" class="hole"/>'
          for x in (CAM_W / 2 - CAM_HOLE_DX / 2, CAM_W / 2 + CAM_HOLE_DX / 2)]
    svg.extend([f'<g transform="translate({sx},{sy})">',
                '<text x="0" y="-14" class="t">카메라 판 (세워서 끼움)</text>',
                f'<polygon points="{pts}" class="plate"/>',
                f'<rect x="{(CAM_W/2-10)*S}" y="{(CAM_H-9)*S}" width="{20*S}" height="{4*S}" rx="{2*S}" class="hole"/>',
                *hl,
                f'<rect x="{(CAM_W/2-12.5)*S}" y="{(CAM_H-CAM_EDGE_Z-24)*S}" width="{25*S}" height="{24*S}" class="ref"/>',
                f'<text x="{CAM_W/2*S}" y="{(CAM_H+TAB_H)*S+16}" class="s" text-anchor="middle">탭 → 위층 홈</text>',
                "</g>"])


def main():
    sheet, svg = Sheet(), []
    plate(sheet, svg, 0, 0, "아래층 5mm (위에서 본 모습)", lower_cut, lower_ref)
    plate(sheet, svg, 230, 0, "위층 3mm (위에서 본 모습)", upper_cut, upper_ref)
    camera_plate(sheet, svg, 460, 0)
    sheet.write_dxf(OUT / "chassis.dxf")
    style = ("<style>.t{font:bold 14px sans-serif}.s{font:11px sans-serif;fill:#333}"
             ".plate{fill:#eaf4fb;stroke:#1f6fae;stroke-width:1.5}.hole{fill:#fff;stroke:#c0392b;stroke-width:1.2}"
             ".ref{fill:none;stroke:#555;stroke-dasharray:4 3}.under{fill:#ddd;stroke:#999;stroke-dasharray:2 2}</style>")
    (OUT / "chassis_preview.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="480" viewBox="0 0 900 480">'
        f'<rect width="900" height="480" fill="#fff"/>{style}{"".join(svg)}</svg>', encoding="utf-8")
    print("wrote", OUT / "chassis.dxf", "and chassis_preview.svg")


if __name__ == "__main__":
    main()
