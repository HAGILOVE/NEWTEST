# 실행 방법 (Quick Start)

## 0. 요구사항

| 항목 | 버전 | 비고 |
|---|---|---|
| Python | 3.9 이상 | 3.11에서 검증 |
| numpy / scipy | 1.24+ / 1.10+ | **필수**. Python 3.13은 numpy≥2.1·scipy≥1.14.1,<br>Python 3.14는 numpy≥2.4·scipy≥1.16.1 필요 |
| gmsh | 4.11+ | 선택. OpenCASCADE 지오메트리 + 사면체 메싱 + STEP/IGES 임포트 |
| matplotlib | 3.7+ | 선택. 그래프 저장용 (HTML 리포트는 없어도 SVG로 그려짐) |

gmsh 없이도 내장 구조격자 메셔로 전체 파이프라인이 돌아감. 다만 CSG·CAD
임포트·곡면 정확도를 쓰려면 gmsh를 넣는 게 맞음.

### Linux에서 gmsh 시스템 라이브러리

gmsh 휠은 X11/OpenGL 공유 라이브러리에 링크돼 있어서, 헤드리스 서버·도커에서는
아래가 없으면 `OSError: libGLU.so.1: cannot open shared object file`이 뜸.

```bash
sudo apt-get install -y libglu1-mesa libxft2 libxinerama1 libxcursor1 \
                        libfontconfig1 libxrender1
```

macOS(`pip install gmsh`)와 Windows는 추가 설치 없이 동작함.

---

## 1. 설치

```bash
unzip aether-em-1.6.0.zip -d aether-em
cd aether-em

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[all]"            # 솔버 + gmsh + matplotlib   (약 30초)
# 또는
pip install -e .                   # 최소 설치 (numpy + scipy만)
```

설치 확인:

```bash
aether-doctor          # 인터프리터·경로·의존성 상태 진단
aether --version
python -c "import gmsh; gmsh.initialize(); print('gmsh OK'); gmsh.finalize()"
```

---

## 2. GUI로 시작하기 (가장 빠름)

```bash
aether gui
```

로컬 서버가 뜨고 브라우저에 작업 공간이 열림. 좌측 프로젝트 트리, 중앙 3D 모델러,
우측 속성창, 하단 메시지 매니저·진행창·스크립팅 콘솔 구성임.

1. 리본 **Home ▸ Template** → `waveguide` 선택 → 바로 풀 수 있는 모델이 생성됨
2. **Simulation ▸ Validate** (F5) 로 점검
3. **Simulation ▸ Analyze All** (F9) → 진행창에서 메싱·적응패스·스윕 진행 확인
4. 끝나면 S-parameter 리포트 탭이 자동으로 열림

```bash
aether gui --template waveguide     # 템플릿으로 바로 시작
aether gui --project my.warp        # 기존 Warps 프로젝트 열기
aether gui --port 8800 --no-browser # 포트 고정, 브라우저 자동실행 끄기
```

파일은 전부 **탐색 창에서 골라서** 열고 저장함 — 경로를 타이핑할 일 없음
(File ▸ Open/Save As, Draw ▸ Import CAD의 Browse…, Results ▸ Export의 Browse…).
Windows에서는 드라이브 목록이 왼쪽에 나오고, **System dialog…** 버튼으로
윈도우 기본 파일 대화상자를 열 수도 있음.

도형 이름은 **자동으로 채워짐** — Box1, Box2, Cylinder1, PerfE1, Rad1,
Port1, Setup1… 비워두고 만들어도 서버가 알아서 이름을 붙임.

3D 뷰에서 **객체를 클릭하면 선택**됨 (Ctrl/Shift+클릭으로 추가 선택,
빈 곳 클릭으로 해제).

**Edit 메뉴**에 실제 설계에 쓰는 편집 기능이 다 들어 있음 —
실행취소/재실행(Ctrl+Z / Ctrl+Y, 40단계, "Undo Move"처럼 작업명 표시),
잘라내기·복사·붙여넣기(Ctrl+X / C / V), 오프셋 붙여넣기,
복사배열(직선 / 축 회전 / 대칭, Ctrl+D), 이동·회전·대칭·스케일.
선택한 객체 여러 개에 한 번에 적용되고, 각각이 실행취소 한 단계임.
복사 개수는 **원본을 포함한 전체 개수**임 (360°에 4개 = 90° 간격).

STEP·IGES 같은 CAD 파일은 **단위가 핵심임**. 파일에는 숫자만 들어 있고
단위는 따로 선언되어 있어서, mm로 선언된 20mm 부품을 m로 읽으면 20m짜리가
되어 화면에 아무것도 안 보이는 것처럼 됨. Import CAD 창에서 파일을 고르면
바로 파일을 읽어서 형식·솔리드 개수·면 개수·실제 크기(mm)·적용 단위를
표시해 줌. 기본은 **Auto**(파일 선언값)이고, 단위를 직접 지정할 수도 있음
(STL/OBJ는 선언 자체가 없어서 mm로 가정함).

**Browse…** 버튼은 Import 창 위에 파일 탐색 창을 겹쳐서 열고, 파일을 고르면
원래 창으로 경로가 채워진 채 돌아옴. 탐색 창 이름란에 전체 경로를 붙여넣어도
됨. 불러온 CAD 객체는 일반 객체와 동일하게 이름·재질 변경, 이동·회전·복사,
boolean, 경계/포트 할당이 가능하고, **속성창에서 단위와 원본 파일을 그대로
바꿀 수 있음** (Modeler ▸ Replace CAD Source…). 이때 객체를 새로 만드는 게
아니라 제자리에서 고치므로 이름·재질·변환·할당된 경계와 포트가 전부 유지됨.

프로젝트를 저장하면 불러온 CAD 파일이 `<프로젝트이름>.cad` 폴더로 함께
복사되므로, 프로젝트를 옮기거나 다른 사람에게 보내도 그대로 열림.

**선택(Select) 기능** — 3D 뷰 우측 툴바 또는 단축키로 모드 전환:
`O` 객체(object) / `F` 면(face) / `E` 모서리(edge). Ctrl+클릭으로 추가 선택,
빈 곳 클릭으로 해제. 상태바에 선택한 면의 **면적**, 모서리의 **길이**가 표시됨.
면을 선택한 뒤 경계조건·포트·메쉬 오퍼레이션을 할당하면 그 면에만 적용됨.
선택 정보는 face index가 아니라 **면의 기하 정보**(면 위의 점·법선·범위)로
저장되므로, 재메싱·adaptive pass·프로젝트 재오픈 후에도 그대로 유지됨.

**메쉬 오퍼레이션** — `Simulation ▸ Add Mesh Operation…` 으로 객체 또는
선택한 면에 최대 요소 길이를 지정해 초기 메쉬를 국부적으로 조밀하게 만듦.
트리의 Mesh 아래에 표시되고 속성창에서 수정·비활성화 가능함.

**면 편집** — `Modeler ▸ Sweep Face Along Normal…` (면을 법선 방향으로
밀어내어 체적 추가), `Modeler ▸ Move Faces…` (면 자체를 이동, 음수면 깎아냄).
객체 이름·재질·할당된 경계와 포트가 그대로 유지되고, 각각 실행취소 1단계임.

**여러 바디로 된 STEP** 은 **바디마다 별도 객체**로 들어옴 (CAD 라벨이 있으면
그 이름 사용). 부품별로 재질·경계를 따로 줄 수 있음. 하나로 합쳐 가져오려면
Import 창에서 *single body* 선택.

**AutoCAD .dxf** 도 바로 읽음. 파일 탐색 창의 CAD 필터에 `.dxf` 가 들어 있고,
포맷을 고르면 실제로 그 포맷만 목록에 남음. 닫힌 외곽선이 sheet 가 되고, 안쪽에 들어있는
외곽선은 구멍으로 잘라냄. 그 다음 `Modeler ▸ Sweep Face Along Normal…` 로
두께를 주면 솔리드가 됨 (예: 안테나 패턴 → 35µm 동박).

**거리·치수 측정** — 선택하면 뷰포트 좌측 하단에 모델 단위로 표시됨:
모서리 1개 → 길이 / 모서리 2개 → 각 길이와 간격 / 면 1개 → 면적과 크기 /
**면 2개 → 두 면 사이 간격** (평행이면 평행 여부와 면간 거리도) / 객체 → 전체
크기와 두 객체 사이 간격. 간격은 중심 간 거리가 아니라 **최단 거리**이고,
측정한 구간이 3D 뷰에 선으로 그려지고 숫자가 그 위에 표시됨.

**마우스로 도형 그리기** — `Draw ▸ Box/Rectangle/Cylinder by points`.
첫 클릭이 원점(객체를 클릭하면 그 객체 위, 빈 곳이면 그리드 평면), 두 번째
클릭이 반대쪽 모서리. 움직이는 동안 외곽선과 치수가 실시간 표시되고, 확정하면
**그 수치가 입력된 상태로 생성 창이 열림**. `S` 스냅 토글, `Esc` 취소.

**경계·포트가 화면에 보임** — 할당된 면 위에 타입별 색으로 그려지고, 우측에
범례가 뜸(클릭하면 속성창으로 이동). 포트의 integration line 도 함께 표시됨.
메쉬 없이도 표시되므로, 엉뚱한 면에 할당된 것을 해석 전에 바로 알 수 있음.

**속성창(PROPERTIES)** — 객체를 선택하면 이름·재질과 함께 **색상·투명도·표시
여부**를 직접 바꿀 수 있음. 기본값은 재질 값이고, 바꾸면 옆에 *reset* 이 생겨
재질 값으로 되돌릴 수 있음. 숨긴 객체는 화면에 안 그려지고 클릭도 안 되지만
모델과 해석에는 그대로 남아 있음.

**마우스 오른쪽 버튼** — 3D 뷰와 프로젝트 트리 모두 컨텍스트 메뉴가 뜸.
3D 뷰: 선택 모드(객체/면/모서리), Assign Boundary·Wave Port·Lumped Port,
Add Mesh Operation, Sweep Face Along Normal, Move Faces, Arrange, Duplicate,
Boolean, Copy/Paste/Delete, Fit All, Properties. 객체 위에서 오른쪽 클릭하면
그 객체가 먼저 선택됨. 트리: 노드 종류에 맞는 항목만 표시됨(객체는 Rename,
Hide, Show All 등, 경계·포트·setup·메쉬 오퍼레이션은 Properties/Delete).

큰 어셈블리는 **파일을 한 번만 읽음** — 파트별 크기 측정·목록·화면 표시가
모두 한 번의 import 에서 나옴 (24바디 기준 6.7초 → 1.3초, 메모리 일정).
한글 폴더명 같은 **비 ASCII 경로**도 처리됨 (OpenCASCADE 가 narrow string 만
받아서 Windows 에서 실패하던 문제). 읽을 수 없는 파일은 어떤 파일이고 무엇을
시도하면 되는지 알려줌.

Warps 데스크탑에서 저장한 `.warp` 파일도 열림. 파일이 손상되어 있어도
**읽을 수 있는 부분은 그대로 열림** — 파싱 안 되는 구문은 원문 그대로 보존하고,
따옴표가 안 닫힌 값은 그 줄에서 끝나며(예전엔 파일 끝까지 삼켜서
`unterminated string near offset 0` 이 났음), 안 닫힌 블록은 복구하고 기록함. 모델러로 만든 프로젝트는 형상이
Parasolid(`.x_b`) 바디로 파일 안에 바이너리로 들어 있는데, 이 바디들은
`<프로젝트이름>.cad` 폴더로 추출되고 객체·재질·경계·포트·해석 설정은 정상적으로
불러와짐. Parasolid 자체는 OpenCASCADE가 읽지 못하므로, Warps에서
Modeler ▸ Export ▸ .step 으로 내보낸 뒤 `Modeler ▸ Replace CAD Source…` 로
연결하면 형상까지 완성됨.

자세한 사용법은 `docs/GUI.md` 참고. 서버는 기본적으로 `127.0.0.1`에만 바인딩되고,
모든 API 호출은 실행마다 새로 만들어지는 토큰을 요구함 (콘솔이 Python을 실행하므로).

## 3. CLI로 30초 만에 첫 해석 돌리기

```bash
mkdir run && cd run

aether new demo.warp --template microstrip   # 예제 프로젝트 생성
aether solve demo.warp                       # 해석 (~1초)
```

출력물이 옆에 같이 떨어짐:

```
demo.s2p              Touchstone S-parameter
demo_sparams.csv      주파수별 dB/위상 표
demo_modes.csv        포트 모드 (β, 차단주파수, Zwave, Zpv)
demo_report.html      브라우저로 여는 리포트 (그래프 포함)
```

### 템플릿 3종

| 템플릿 | 구조 | 소요 시간 | 확인 포인트 |
|---|---|---|---|
| `microstrip` | 평행판 선로 + lumped port | **~1 초** | `Z0 = η0·h/w = 37.67 Ω`, S11 < −46 dB |
| `coax` | 50 Ω 공기 동축 + wave port + 적분선 | ~8 초 | TEM(β=k0), `Zpv ≈ 50 Ω` |
| `waveguide` | WR-90 도파관, 적응 메시 3패스 | ~16 초 | TE10 `fc = 6.557 GHz`, S11 < −38 dB |

```bash
aether new wg.warp --template waveguide && aether solve wg.warp
```

---

## 4. CLI 명령 전체

```bash
aether gui                                        # 그래픽 작업 공간 실행
aether new       proj.warp --template waveguide   # 시작용 프로젝트 생성
aether info      proj.warp                        # .warp / .sNp / CAD 파일 들여다보기
aether validate  proj.warp                        # 파싱→쓰기 바이트 무결성 증명
aether mesh      proj.warp --size 0.003 --out m.vtu
aether solve     proj.warp --order 2 --passes 6 --fields
aether convert   meas.s2p out.ts --format MA      # 포맷 변환
aether materials rogers                           # 재질 라이브러리 검색
```

`solve` 주요 옵션:

| 옵션 | 뜻 |
|---|---|
| `--order 1\|2` | 기저 차수. 2차는 같은 메시에서 오차가 2~3자릿수 작음 |
| `--passes N` | 적응 패스 상한 |
| `--no-adaptive` | 적응 끄고 초기 메시로 1회 해석 (빠른 확인용) |
| `--fields` | 필드를 `.vtu`로 저장 (ParaView에서 열림) |
| `--backend occ\|builtin` | 메셔 선택 |
| `--out BASE` | 출력 파일 접두어 |
| `-v` | 상세 로그 (에러 시 traceback까지) |

---

## 5. 파이썬 API로 직접 모델링

```python
import aether as ae

d = ae.Design("wr90", solution_type="driven_modal", units="mm")
d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "30mm"), "vacuum")
d.add_wave_port("p1", axis="z", value=0)
d.add_wave_port("p2", axis="z", value="30mm")
d.assign_pec_outer()                          # 포트 빼고 전부 금속벽

setup = d.add_setup("Setup1", frequency="10GHz", max_passes=6, delta_s=0.02)
setup.add_sweep("XBand", "8.2GHz", "12.4GHz", 43)

sol = d.solve()
print(sol.summary())

sol.sparams.write_touchstone("wr90.s2p")
sol.sparams.renormalize(50.0).to_csv("wr90_50ohm.csv")

m = sol.port_mode(10e9, port=0, mode=0)
print(m.kind, m.beta, m.f_cut / 1e9, m.Z_port)
```

길이·주파수는 `"22.86mm"`, `"10GHz"`, `"100mil"` 같은 **단위 문자열**을 그대로
받고, 내부는 전부 SI로 변환해서 계산함.

### CSG · CAD 임포트

```python
coax = ae.Cylinder((0, 0, 0), "2.3mm", "20mm") - ae.Cylinder((0, 0, "-1mm"), "1mm", "22mm")
d.add_solid("diel", coax, "vacuum")

d.add_solid("part", ae.import_cad("housing.step"), "vacuum")   # STEP/IGES/BREP/STL
```

### 경계 조건

```python
d.assign_pec("Walls", ae.OuterSelector())
d.assign_radiation("Rad1", ae.BoundingBoxFaceSelector("+z"))
d.assign_finite_conductivity("Cu", sel, material="copper",
                             thickness="35um", roughness="1um")
d.assign_boundary("PMC", "pmc", ae.PlaneSelector("y", 0))
d.assign_lumped_rlc("R1", sel, R=50.0)
```

---

## 6. Warps 프로젝트 열고 되쓰기

```python
import aether as ae

design, report = ae.open_warps("project.warp")
print(report)                 # 매핑 안 된 항목이 전부 여기 나옴
print(design.summary())

design.get_setup("Setup1").frequency = 12e9
ae.save_warps(design, "project_v2.warp", mode="update")
```

`mode="update"`는 원본 트리를 그 자리에서 고침 — **바꾼 문장만** 다시 렌더링하므로
mesh operation·optimetrics·report 정의·field overlay가 사라질 수 없음.
`mode="create"`는 Aether 모델에서 새 프로젝트를 통째로 생성함.

파일이 안 깨지는지 직접 확인:

```bash
aether validate project.warp
# → round-trip byte-identical : YES
```

---

## 7. 예제 스크립트

```bash
python examples/01_rectangular_waveguide.py   # WR-90, 해석해와 위상 비교      ~14초
python examples/02_coaxial_line.py            # TEM, 적분선, Zpv 추출
python examples/03_lumped_port_line.py        # 평행판 선로, 정합/부정합       ~2초
python examples/04_iris_coupled_cavity.py     # 내부 PEC 시트, 1극 대역통과
python examples/05_warps_roundtrip.py          # .warp 읽기/수정/쓰기           ~1초
python examples/06_cad_import.py              # STEP 내보내기→가져오기→해석
```

---

## 8. 자체 검증 돌리기

```bash
pytest -q            # 169개 (솔버 해석해 대조 + GUI API/서버 + 브라우저 UI)
pytest -q -m "not slow"
pytest tests/test_physics.py -q -k waveguide
```

gmsh가 없으면 OCC 백엔드가 필요한 테스트는 자동 skip됨.

---

## 9. Windows에서 Python이 여러 개일 때 (가장 흔한 사고)

증상: `aether gui` 실행 시 numpy C 확장 임포트 실패, 그리고 에러 안에
**서로 다른 두 Python 경로**가 보임.

```
The Python version is: Python3.14 from "C:\Python314\python.exe"
The NumPy version is: "1.26.4"
  ...\Python312\Lib\site-packages\numpy\...
```

Python 3.14로 실행되는데 numpy는 **3.12의 site-packages**에서 로드된 것임.
C 확장(.pyd)은 인터프리터 버전마다 ABI가 달라 절대 공유될 수 없음. 원인은
거의 항상 `PYTHONPATH` 환경변수가 다른 Python의 site-packages를 가리키는 것임.

진단은 한 줄로 끝남:

```cmd
aether-doctor
```

실행 중인 인터프리터, ABI 태그, `PYTHONPATH`, numpy/scipy가 실제로 어디서
발견됐는지와 어떤 버전인지, 그리고 정확한 해결 명령을 출력함.

### 해결 방법 A — 가상환경 (권장)

```cmd
set PYTHONPATH=
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[all]"
aether gui
```

### 해결 방법 B — Python 3.14를 그대로 쓰기

3.14도 지원됨. 다만 **numpy 2.4 이상, scipy 1.16.1 이상**이 필요함
(numpy 1.26.4는 3.14용 휠이 아예 없음).

```cmd
set PYTHONPATH=
py -3.14 -m pip install -U "numpy>=2.4" "scipy>=1.16.1"
py -3.14 -m pip install -e ".[all]"
py -3.14 -m aether.cli gui
```

`PYTHONPATH`를 영구적으로 지우려면: 시스템 속성 → 환경 변수 → `PYTHONPATH` 삭제.

### 어떤 Python들이 깔려 있는지 확인

```cmd
py -0p
```

`pip install` 이 어느 인터프리터로 가는지 헷갈리면 항상
`py -3.12 -m pip ...` 처럼 **인터프리터를 명시**해서 쓰는 게 안전함.

## 10. 자주 겪는 문제

| 증상 | 원인 / 해결 |
|---|---|
| `OSError: libGLU.so.1` | 위 apt 패키지 설치 |
| `imported CAD requires the OCC backend` | `pip install gmsh` |
| `port 'p1' selected 0 triangles` | 포트 평면 좌표/단위 확인. `aether mesh --out m.vtu`로 메시를 ParaView에서 보면 바로 보임 |
| `model validation failed` | `design.validate()`가 원인 리스트를 반환함 (포트 없음, setup 없음, 이름 중복 등) |
| 적응이 ΔS에 못 미침 | `--passes` 올리거나 `--order 2`로 전환. 2차 기저가 같은 메시에서 훨씬 정확함 |
| 큰 모델에서 메모리 부족 | `d.config.solver.linear_solver = "iterative"` (GMRES+ILU) |
| Touchstone 쓸 때 임피던스 경고 | wave port는 Z가 주파수에 따라 변함. `renormalize(50.0)` 후 쓰거나 `version=2.0`으로 쓰기 |
| 해석이 오래 걸림 | 포트 면 메시가 조밀하면 모달 고유해석이 지배적임. 초기 `--size`를 키우고 적응에 맡기는 편이 빠름 |
| GUI에서 3D 뷰가 비어 있음 | 브라우저 WebGL 비활성화. 다른 브라우저로 열거나 하드웨어 가속을 켤 것 |
| GUI 접속이 403 | URL의 `?token=...` 이 빠졌음. 터미널에 출력된 주소를 그대로 사용 |
| numpy C 확장 임포트 실패 | Python 버전 교차 오염. `aether-doctor` 실행 → 위 9절 참고 |
| `ModuleNotFoundError: numpy.core._multiarray_umath` | 같은 원인. numpy가 다른 Python의 site-packages에서 로드됨 |

성능 감각: WR-90 2포트 기준 초기 메시(300 tet) 0.5초, 적응 3패스(3천 tet) 14초,
4패스(3만 tet, 39k DOF) 약 100초 — 대부분 포트 모달 해석과 희소 LU에서 나감.
