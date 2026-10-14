# Aether EM 1.8.0 — 3D full-wave FEM 해석 툴 (HFSS 호환 워크플로)

Maxwell 방정식을 주파수 영역에서 직접 푸는 3D FEM 솔버임. 사면체 + Nédélec edge element(HFSS와 같은 수치 기반)를 쓰고, HFSS `.aedt` 프로젝트를 읽고 쓸 수 있음. 브라우저 기반 데스크톱 GUI(`aether gui`)가 HFSS와 같은 흐름(Modeler → Boundary/Port → Setup → Analyze → Results)으로 동작함.

```bash
aether gui                                      # 빈 프로젝트
aether gui --project examples/dipole_antenna.aedt   # 완성된 다이폴 안테나 예제
```

Windows: `SETUP_WINDOWS.cmd`(최초 1회, 인터넷 필요) → `START_WINDOWS.cmd`. Python 3.12 권장.

## 1.8.0에서 바뀐 것

| 영역 | 내용 |
|---|---|
| 솔버 | 실제 **Interpolating / Fast** 스윕, **Eigenmode**(공진주파수·Q), 원거리장·안테나 지표, **최적화(Optimetrics)** |
| 해석 설정 | HFSS와 같은 Setup 항목(최소/연속 수렴 패스, 패스당 세분화 %, 기저 차수), Linear Count/Step/Log/Single 스윕, Setup·Sweep 편집 |
| 결과 | **E / H 필드, 표면 전류(Js)**, 컷 플레인, 위상 슬라이더·**시간 애니메이션(필드·방사패턴)**, 벡터 화살표, 방사패턴(극좌표/직교/3D), 이득·효율 표 |
| 내보내기 | Save As ▸ **three.js 3D viewer (.html)** — 모델과 결과(E/H/전류/방사)를 인터넷 없이 브라우저에서 3D로 보고 애니메이션 |
| 모델링 | XY/YZ/ZX 작업 평면, 면에서 평면 가져오기, **Tab으로 수치 입력**, circle/sphere/cone, 그린 면을 포트로 지정 |
| 편집 | 다중 선택 일괄 속성 변경(재료·색·투명도), 기본 색상 팔레트 + 상세 색 |
| 버그 수정 | Radiation 경계가 안테나 금속에 걸리던 문제, 직접 솔버 정렬(최대 85배 빠름), 메시 연산/Netgen 크래시 등 ([CHANGELOG](CHANGELOG.md)) |

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"      # numpy/scipy + gmsh(CAD·메시) + matplotlib
```

gmsh가 없으면 내장 구조형 메셔로 동작하지만 CAD 가져오기와 곡면 형상은 제한됨. 헤드리스 Linux에서는 `libglu1-mesa libxft2 libxinerama1 libxcursor1 libfontconfig1 libxrender1`가 필요함. 시작 문제는 `aether doctor`로 진단.

## 예제

`examples/`에 9개의 **완성된 `.aedt` 프로젝트**(다이폴·패치 안테나, 도파관, 필터, 동축, 공동 공진기, 매개변수 슬랩)와 사용법이 있음 → [examples/README.md](examples/README.md).
다이폴 예제는 그린 면에 Lumped Port, Radiation 경계, 2차 요소가 설정되어 있고 공진 2.95 GHz에서 입력임피던스 ≈ 69 Ω, 지향성 2.18 dBi(이론 2.15 dBi), 축 방향 null이 나옴.

```python
import aether as ae

d, _ = ae.open_hfss("examples/dipole_antenna.aedt")
sol = d.solve(save_fields=True)
print(sol.summary())
ff = sol.farfield(freq=3e9)
print(ff.summary()["peakDirectivityDbi"])
```

## 기능

| 구분 | 내용 |
|---|---|
| 지오메트리 | Box, Cylinder, Sphere, Cone, Torus, Rectangle/Circle(면), 불리언, 변환, 변수·수식 치수. STEP/IGES/BREP/STL/DXF 가져오기 |
| 재료 | 40+ 내장 재료, 상수 tanδ, Debye·Drude·Lorentz·Djordjevic-Sarkar, 측정 데이터 |
| 경계 | PEC, PMC, 표면 임피던스, 유한 도전율(거칠기), Radiation(1차 흡수), Lumped RLC, 대칭 |
| 포트 | Wave Port(2D 모드 해석, 다중 모드, de-embed, 재정규화, 적분선), Lumped Port(그린 면 지정) |
| 해석 | Driven Modal, **Eigenmode**; 1·2차 요소; 적응형 메시; Discrete / **Interpolating** / **Fast** 스윕 |
| 후처리 | S/Z/Y/ABCD, 혼합모드, VSWR, 군지연, **E/H/Js 필드**, **원거리장·이득·효율**, Touchstone/CSV/VTK/HTML |
| 최적화 | 변수 범위 + 목표(goal), Nelder-Mead / Pattern / L-BFGS-B / Differential evolution |
| 파일 | `.aedt`/`.aedtz` 읽기·쓰기(원문 보존 round trip), Touchstone `.sNp` |

지원하지 않는 것(숨기지 않고 적음): PML, 주기 경계/Floquet 포트, Terminal(차동) 솔루션, ACIS/Parasolid 바이너리 직접 읽기(STEP으로 내보낸 뒤 `Modeler ▸ Repair Bodies`로 연결), 방사 경계가 있는 Eigenmode. HFSS와의 수치 일치는 보증하지 않으며, 중요한 설계는 실측 또는 독립 솔버로 검증해야 함.

## GUI 사용 흐름

1. **Draw** — `Draw ▸ Draw Box by Points`: 평면 선택(또는 `P`), 클릭하거나 `Tab`으로 값 입력, `Enter` 확정. 면(Rectangle/Circle)도 같은 방식.
2. **재료·색** — 객체 선택(여러 개 가능) → 속성창에서 재료·색·투명도.
3. **경계·포트** — 면/객체 선택 → 우클릭 `Assign Boundary…`, `Assign Wave Port…`, `Assign Lumped Port…`(두 도체 면을 클릭해 만드는 `Port (pick)`도 있음).
4. **Setup** — `Simulation ▸ Add Solution Setup…`(해석 주파수, 최대 패스, ΔS …), `Add Frequency Sweep…`.
5. **Analyze** — `Validation Check`(F5) → `Analyze All`(F9, 필드가 필요하면 *Save fields*).
6. **Results** — S-파라미터, 방사패턴, E/H/표면 전류, 컷 플레인, Eigenmode 표. `Tools ▸ Optimization…`.

## 명령줄

```bash
aether gui [--project file.aedt] [--template waveguide]
aether solve project.aedt --order 2 --fields      # .sNp, CSV, HTML 리포트 생성
aether new demo.aedt --template microstrip
aether info project.aedt
aether validate project.aedt                      # parse/write round trip 검증
aether mesh project.aedt --out m.vtu
```

## 정확도 (해석해 대비)

| 케이스 | 해석해 | Aether | 오차 |
|---|---|---|---|
| WR-90 TE10 차단주파수 | 6.5571 GHz | 6.5600 GHz | 0.04 % |
| 직사각 공동 TE101 (2차) | 9.0076 GHz | 9.0078 GHz | 0.002 % |
| 유전체 충전 공동 Q | 1/tanδ = 1000 | 1000.0003 | 3e-7 |
| 구리 공동 Q (Pozar 6.46) | 9182 | 9178 | 0.04 % |
| Hertz 다이폴 방사전력 | 3.9506 | 3.9539 | 0.08 % |
| 반파 다이폴 Zin / 지향성 | 73 Ω / 2.15 dBi | 69 Ω / 2.18 dBi | 4 Ω / 0.03 dB |
| 균일 도파관 S21 위상 (2차) | 정확 | — | 0.002° |

## 문서·테스트

[docs/QUICKSTART.md](docs/QUICKSTART.md) · [docs/GUI.md](docs/GUI.md) · [docs/THEORY.md](docs/THEORY.md) · [docs/DESIGN.md](docs/DESIGN.md) · [docs/HFSS_INTEROP.md](docs/HFSS_INTEROP.md) · [docs/VALIDATION.md](docs/VALIDATION.md) · [docs/UPGRADE_1.8.0_KO.md](docs/UPGRADE_1.8.0_KO.md)

```bash
pytest -q                                  # 해석해 대비 솔버 테스트 + GUI API
pip install playwright && pytest -q tests/test_gui_*  # 브라우저(Chromium) 테스트
```
