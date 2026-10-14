# 예제 모음

모든 `.aedt` 프로젝트는 **형상·재료·경계·포트·Setup·Sweep이 모두 들어 있는 완성본**임.
열어서 `F9`(Analyze All)만 누르면 해석되고, 결과는 Results 메뉴에서 바로 볼 수 있음.

```bash
aether gui --project examples/dipole_antenna.aedt     # GUI에서 열기
python examples/build_examples.py                     # 모든 .aedt 다시 생성
python examples/build_examples.py --verify            # 생성 + 실제로 풀어서 결과 확인
```

Windows는 `START_WINDOWS.cmd` 실행 후 File ▸ Open Project로 `examples\*.aedt`를 열면 됨.

## 프로젝트 파일(.aedt)

| 파일 | 내용 | 무엇을 보는 예제인가 | 해석 시간 |
|---|---|---|---|
| `dipole_antenna.aedt` | 3 GHz 반파장 다이폴, **그린 면(sheet)에 Lumped Port**, Radiation 경계, 2차 요소 | 공진·입력임피던스, 방사패턴/이득, E·H 필드, **표면 전류** | 약 3분 |
| `patch_antenna.aedt` | 2.4 GHz 마이크로스트립 패치(FR-4), 접지면 PEC, 패치 sheet PEC, 급전 포트, Radiation | 패치 안테나 S11 공진, 방사패턴, 필드 | 약 1분 |
| `wr90_waveguide.aedt` | WR-90 직선 도파관, **Wave Port** 2개, Interpolating sweep | 포트 모드(TE10 차단 6.56 GHz), S21 위상, 보간 스윕 | 약 30초 |
| `iris_filter.aedt` | 아이리스 2개로 만든 1극 대역통과 필터, Fast sweep | 내부 PEC sheet, 공진 필터 응답, Fast(reduced-basis) sweep | 약 1분 |
| `coax_line.aedt` | 50 Ω 동축선, Wave Port + **적분선** | TEM 모드, 선로 임피던스 V²/2P | 약 20초 |
| `parallel_plate_lumped.aedt` | 평행판 선로, Lumped Port, 2·Z0 종단 | 해석해 \|Γ\| = 1/3 와 비교 | 수 초 |
| `cavity_eigenmode.aedt` | 30×15×20 mm PEC 공동, **Eigenmode** 5개 | 공진주파수(해석해와 비교), 모드별 E 필드 | 수 초 |
| `copper_cavity_eigenmode.aedt` | 구리 벽 공동, 유한 도전율 경계 | 도체 손실 Q (Pozar 식과 비교) | 수 초 |
| `slab_matching_parametric.aedt` | WR-90 + 유전체 슬랩, 두께가 설계변수 `T` | Tools ▸ **Optimization** / Parameter Study | 풀이당 수 초 |

## 파이썬 스크립트

| 스크립트 | 내용 |
|---|---|
| `10_dipole_antenna.py` | 다이폴을 풀고 공진, Zin, 지향성·이득·효율·전후방비를 출력 |
| `11_optimize_slab.py` | 슬랩 두께를 최적화해 반사 null을 10 GHz에 맞춤(해석해 11.96 mm, 거친 1차 메시는 11.7 mm 부근에서 수렴) |
| `12_sweep_strategies.py` | Discrete / Interpolating / Fast 스윕의 풀이 횟수·시간·오차 비교 |
| `13_eigenmode_cavity.py` | 공동 공진주파수·Q를 해석해와 비교 |
| `01`–`06_*.py` | 기존 API 예제(도파관, 동축, 평행판, 아이리스, .aedt 왕복, CAD 가져오기) |

## 다이폴 예제로 보는 GUI 작업 순서

1. `File ▸ Open Project…` → `dipole_antenna.aedt`. 트리에 `Arm_Top/Arm_Bottom`(구리색 PEC), `Feed`(빨간 sheet), 경계 `Radiation`, 포트 `Port1`, Setup1/Sweep1이 보임.
2. `Simulation ▸ Validation Check`(F5) → `Analyze All`(F9).
3. `Results ▸ Create Modal S-Parameter Report` → S11, `S-Parameter Metrics…`로 대역폭.
4. `Results ▸ Far Field Radiation Pattern…` → 극좌표 8자 패턴과 안테나 파라미터 표(지향성·이득·효율), `3D pattern`.
5. `Results ▸ Surface Current |Js|` → 팔을 따라 흐르는 전류. 패널의 **Instantaneous + ▶ Animate**로 위상을 돌리면 전류가 흐르는 것을 볼 수 있음. `Vector arrows`를 켜면 방향 표시.
6. `Results ▸ Field on Cut Plane` → 안테나를 지나는 평면의 |E|, 위치 슬라이더로 평면을 이동.

## 직접 만들 때(마우스 + Tab 입력)

- `Draw ▸ Draw Box by Points` 등을 선택하면 패널이 뜸. **Plane**에서 XY / YZ / ZX 중 작업 평면을 고르거나 `P` 키로 순환.
- 첫 점은 클릭하거나 `Tab`을 눌러 좌표를 입력. 다음 점은 `Tab`으로 크기(dX, dY, 높이)를 입력하고 `Enter`로 확정. 마우스를 움직이는 동안 숫자는 덮어써지지 않으며, 클릭하면 입력한 값이 확정됨. `Esc`는 한 단계 뒤로.
- 기존 면 위에 그릴 때는 **Plane from face**가 켜진 상태에서 면 위로 마우스를 가져가면 그 면의 평면이 작업 평면이 됨.
- 면(Rectangle / Circle)을 그린 뒤 선택하고 우클릭 ▸ **Assign Lumped Port… / Assign Wave Port…** 로 포트를 지정.
- 객체를 여러 개 선택(Ctrl+클릭, Ctrl+드래그)하면 속성창이 일괄 편집 모드가 되어 재료·색·투명도를 한 번에 바꿈.
