# Aether EM 1.7.0 — 사용·검증·개발 안내

2026-09-06. 첨부된 1.6.0 소스를 기반으로 파일·편집 문제를 수정한 1.6.1의 변경과, 이번 파라미터 설계 기능을 모두 포함함.

## 1. 이번 버전의 의미

실제로 동작하는 설계·해석 흐름을 확장한 개발 버전임. HFSS 전체 기능·정확도·native project 호환을 달성한 제품은 아님. 동일한 FEM 계열이라는 사실만으로 검증된 상용 솔버와 같은 정확도를 주장할 수 없음.

| 영역 | 구현·개선 내용 | 적용 범위 |
|---|---|---|
| 프로젝트 파일 | AEDT/AEDTZ 열기, 지원 항목 편집 저장, Save As, 임시 파일→최종 교체, 이전 저장 `.bak` | native HFSS 전체 history 호환은 아님 |
| CAD 보관 | 내용 기반 CAD 부속 파일명, AEDTZ 안에 CAD 동봉, 이동 후 재열기 | AEDT는 동명의 `.cad` 폴더도 함께 전달 |
| CAD 가져오기 | 기존 STEP/IGES/BREP/STL/OBJ 및 DXF importer 유지 | 형식·엔티티 제한은 기존 importer 범위. Native CAD는 OCC 필요 |
| CAD 내보내기 | 선택/전체 객체 STL, STEP/STP, 기존 파일 보호 | STEP는 OCC 필요. 재불러오기 크기 검증 실패 시 저장 거부 |
| 치수 편집 | Box/Cylinder/Sphere/Cone/Torus/Rectangle의 원래 치수·변수식 편집 | 이동·회전·배율 이력은 유지 |
| 변수 | 단위 검증, 종속식, 순환 참조 거부, 형상 재생성, 저장·재열기 | 기본 도형과 Boolean/profile 내부의 연결된 기본 도형 |
| 측정 | 객체 XYZ, 거리·축별 차이·각도·3점 원·선분 간격·면 측정, CSV | 면적·곡선 picking은 tessellation 범위 |
| 기본 도형 물성 | 실제 체적, 일부 도형 면적, 반지름·직경·높이 | Boolean 체적을 bbox 체적으로 대신 표시하지 않음 |
| 편집 안정성 | Undo/Redo, 실패 시 되돌림, Cut 복구, 계산 중 편집 제한 | 외부 파일을 바꾸는 Python 스크립트는 Undo 대상 아님 |
| 해석 제어 | 최대 Mesh 크기, 선형 solver, 허용 오차, 연속 수렴 횟수 저장 | 실제 solver 설정으로 전달 |
| Parameter Study | 변수 한 개에 최대 50조건, 설계 복사본으로 실제 FEM 수행 | 치수 변수 대상. 고정 좌표 포트·경계는 별도 검토 |
| 결과 비교 | 조건별 S11 그래프, 색상 대응 표, 요약·곡선 CSV | 메모리 보관. 편집/종료 전에 CSV 내보내기 |
| 해석 취소 | 주파수·Mesh·adaptive 단계 사이에서 취소 | 실행 중인 sparse solve나 OCC 호출을 즉시 중단하지는 않음 |
| 사전 진단 | 미지원 물리 조건·치수·setup·sweep·Mesh 대상 점검, 대략적 요소 수 | 해석 정확도 인증이나 정밀 RAM 예측은 아님 |
| RF 결과 지표 | 샘플 최소 Sii, 주파수 marker, 임계 반사계수 대역, 수동성·상호성 | 교차점은 dB 선형 보간, 최소점·marker는 계산한 주파수 샘플 |
| Air Region | 물리 형상을 뺀 주변 공기와 6면 1차 Radiation 경계 생성 | PML 아님. 기존 전체 외곽 PEC 등과 충돌하면 생성 거부 |

## 2. Windows 실행

1. ZIP을 새 폴더에 완전히 압축 해제해야 함. 기존 설치 폴더에 파일 일부만 덮어쓰지 않는 편이 안전함.
2. Python 3.12가 설치된 상태에서 `START_WINDOWS.cmd`를 실행함.
3. 첫 실행은 프로젝트 전용 `.venv`를 생성하고 NumPy/SciPy/gmsh를 설치하므로 인터넷이 필요함.
4. 의존성 검사에 성공하면 로컬 브라우저 작업창을 열며, 터미널을 닫으면 서버가 종료됨.
5. 설치 복구: `SETUP_WINDOWS.cmd`. 환경 검사만: `CHECK_WINDOWS.cmd`.

개발자 직접 실행:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[mesh,dev]"
.venv\Scripts\python -m aether.cli gui
```

기본 형상과 builtin FEM만 사용할 개발자는 `pip install -e .` 후 `python -m aether.cli gui`로 시작할 수 있음. 이 경우 CAD/Boolean 정밀 표시 기능이 제한됨. `run.py` 기본 런처는 부분 동작을 정상 시작으로 오인하지 않도록 CAD 커널까지 검사함.

Linux에서는 gmsh wheel 외에도 OS의 OpenGL/GLU 라이브러리가 필요할 수 있음. 이번 실행 환경에서는 OCC를 사용할 수 없어 CAD 관련 실행 검증은 미완료임. Windows와 브라우저 전체 클릭 흐름도 이번 환경에서 직접 검증하지 못했음.

## 3. 바로 해볼 수 있는 예제

`examples/parametric_wr90.aedtz`를 Open Project로 열면 다음 모델이 표시됨.

- 진공 WR-90 직사각 도파관, W=22.86mm, H=10.16mm, L=20mm.
- z=0, z=20mm의 Wave Port와 외곽 PEC.
- 10GHz setup, 8~12GHz의 9개 주파수, 최대 요소 크기 4mm.

### 치수 편집과 보관 확인

1. Guide 객체 선택 → Edit의 **Edit Dimensions / Expressions** 또는 Modeler의 **Parameters**.
2. size의 X 값을 `W` 또는 `W/2`로 입력함.
3. Edit/Tools의 **Design Variables**에서 `W = 24mm`로 바꾸고 Apply and rebuild.
4. M → Calculate에서 XYZ 크기 확인.
5. Save As로 새 `.aedtz` 저장 → 다시 열기 → 변수식과 치수 유지 확인.
6. Undo/Redo로 변수·도형 변경을 되돌릴 수 있음.

`L`은 예제의 포트 z좌표와 연결되지 않았으므로 L을 바꾸면 출구 포트도 다시 지정해야 함. 처음에는 W만 변경하여 시험하는 것이 적절함.

### Parameter Study

1. Simulation/Tools의 **Parameter Study**에서 변수 W를 선택함.
2. 값 칸에 아래처럼 한 줄에 하나씩 입력함.

```text
21mm
22.86mm
24mm
```

3. Setup1, backend builtin, 필요 시 case별 adaptive를 선택하고 실행함.
4. Study Results에서 진행 상태, 각 조건의 최소 S11, 비교 곡선을 확인함.
5. Export summary CSV와 Export curves CSV로 보관함.

각 조건은 원본 설계 복사본에서 실제 FEM을 수행하며, 원본 치수와 기존 단일 해석 결과를 덮어쓰지 않음. 단순한 균일 도파관은 모든 조건에서 거의 정합되므로 큰 S11 차이가 나지 않는 것이 정상임. 이 기능은 범용 다변수 optimizer나 HFSS Optimetrics 전체 구현이 아님.

Study 실행 버튼을 다시 누르거나 해석 중 형상을 수정하면 차단됨. Cancel은 현재 계산 단계가 끝날 때 적용되며, 이미 완료한 Study 조건은 남음. 중단된 조건을 가짜 결과로 채우지 않음.

## 4. 변수식 문법과 단위

```text
W = 22.86mm
H = W/2
Gap = max(0.2mm, W/100)
R = sqrt(W*W)/4
Offset = W*sin(30deg)
```

지원 연산: `+ - * / **`, 괄호, `sqrt`, `abs`, `min`, `max`, `sin`, `cos`, `tan`, `pi`.

지원 단위: m/cm/mm/um/nm/mil/in, Hz/kHz/MHz/GHz, deg/rad. 이름은 영문자·숫자·밑줄을 사용하며 pi/q는 예약어임. `$`를 포함한 HFSS 변수 문법 전체를 새 editor가 지원하는 것은 아님.

- `1mm + 1GHz`, 알 수 없는 단위, 음수 크기, 순환 참조는 오류임.
- 좌표와 크기에 직접 입력한 숫자 문자열은 표시 단위로 해석함. 변수에는 `W=10mm`처럼 단위를 명시해야 함.
- 기존 Python/API의 실제 숫자형 길이는 SI m임. 문자열 `"10"`과 Python 숫자 `10`은 같은 의미가 아님.
- 변수는 도형의 원래 치수에 연결됨. 이후 scale이 2배이면 W를 10mm로 바꾸어도 최종 너비는 20mm임.
- imported CAD의 BREP 자체를 변수식으로 재설계하지 않음. CAD 소스를 수정한 뒤 Replace CAD Source를 사용해야 함.
- 주파수 변수 선언은 가능하지만 이 editor의 변수 재생성 대상은 형상임. setup/sweep 주파수는 해석 설정에서 지정해야 함.

## 5. 측정과 편집 구분

**Measure**는 읽기 작업이며 **Edit Dimensions / Expressions**와 **Resize**는 형상을 바꾸는 작업임.

- Primitive Dimensions: Box의 size, Cylinder의 radius/height처럼 원래 설계 값을 변경함.
- Resize: 최종 XYZ 외접 범위를 목표값에 맞게 scale함. 비균일 scale은 원을 타원으로 바꿀 수 있음.
- 회전된 구가 더 큰 큐브로 측정되던 문제와 원뿔·토러스의 과도한 외접 크기를 수정했음.
- 기본 solid의 실제 체적은 affine 변환의 행렬식을 적용하여 계산함. 구·상자·sheet의 면적도 해당 해석식을 적용함.
- 반지름·직경은 원형을 유지하는 변환일 때만 표시함. 비균일 scale로 타원이 된 경우 임의의 반지름 하나를 표시하지 않음.
- Boolean 외접 범위, 부분 Cylinder의 외접 범위는 보수적인 범위일 수 있음.
- 두 객체의 bbox 간격은 실제 표면 clearance의 하한임. 면 간격은 샘플링 근사임. 정밀 기구 간섭 판정으로 사용하면 안 됨.
- 화면 클릭 측정은 표시용 surface/작업 평면과 근접 endpoint를 이용함. BREP의 원본 vertex를 정밀 snap한 값과 다를 수 있음.

기존 측정 도구의 상세 클릭 방법, 단위와 CSV 형식은 `UPGRADE_1.6.1_KO.md` 3~4절 참고.

## 6. CAD 내보내기와 파일 보호

File → Export CAD Geometry에서 STL/STEP과 선택 범위를 지정함.

STL은 surface triangle 좌표이며 표준 단위 필드가 없음. 받는 프로그램에서 선택한 단위를 다시 지정해야 함. Boolean/Imported 형상을 bbox로 바꿔 내보내는 fallback은 금지했음. OCC 없이 지원하지 못하는 형상은 명확한 오류로 종료됨.

STEP는 실제 OCC 형상을 작성하고, 재불러온 SI bounds가 원형상과 맞는지 확인한 뒤 대상 파일을 교체함. STEP 내보내기 코드는 추가했지만 이 환경의 OCC 부재로 성공 실행을 검증하지 못했음. 조건부 테스트 `test_step_export_reimport_dimensions`를 CAD 환경에서 실행해야 함. Gmsh 단위 설정 참고: https://gmsh.info/doc/texinfo/

프로젝트의 포트·재료·변수식·해석 설정은 CAD 내보내기에 포함되지 않음. 전체 작업 보관에는 `.aedtz`를 사용함. S-parameter/field/Study 결과는 별도 결과 export로 보관해야 하며 프로젝트 저장이 계산 결과 전체를 보관하지는 않음.

## 7. 아직 HFSS 수준이 아닌 부분

| 기능 | 상태와 다음 검증 |
|---|---|
| Driven Modal FEM | 기존 1/2차 요소와 적응 Mesh 유지, WR-90 analytic benchmark 수행 |
| Native AEDT | 지원 항목 변환. 암호화·binary/미지원 history 포함 임의 파일 전체 호환 불가 |
| Eigenmode / Driven Terminal | 현재 solver 미구현. 실행 전 오류 처리 |
| PML / periodic / Floquet | 미구현. 미지원 boundary로 실행 차단 |
| Fast / Interpolating Sweep | 기존 이름을 읽지만 실제로 각 주파수 discrete solve 수행. ROM 가속 없음 |
| Geometry-linked assignments | 변수 재생성 후 고정 좌표 포트·경계의 자동 추적 미구현 |
| Radiation / Far field | 기존 1차 radiation·후처리 코드. 임의 안테나의 Gain/효율 정확도는 별도 검증 필요 |
| CAD kernel / Windows / browser | 이번 배포 환경에서 해당 통합 실행 검증 미완료 |
| 상용 대형 해석 | HPC 분산 계산, 산업 규모 meshing robustness, 광범위 회귀 corpus 미완료 |

상용화의 다음 우선순위는 기능 버튼을 더 늘리는 것이 아니라 (1) Windows/OCC/CAD 자동시험, (2) 포트·면 topology 참조의 변수 추적, (3) 동축선·microstrip·안테나의 mesh/radiation 수렴 검증과 HFSS/실측 교차 비교, (4) PML·Eigenmode·주기경계의 독립 구현·수치검증임.

## 8. 개발자 검증 재현

```powershell
.venv\Scripts\python -m pip install -e ".[mesh,dev]"
.venv\Scripts\python -m pytest --junitxml=validation-tests.xml
.venv\Scripts\python validate_release.py --output validation-local.json
```

`validate_release.py`는 pytest나 OCC 없이도 설치된 NumPy/SciPy로 실제 FEM benchmark와 파라미터 저장·재열기를 수행함. 실행 결과와 입력 조건은 `benchmark-1.7.0.json`에 포함함. `test-results-1.7.0.xml`은 전체 회귀시험 원본임. Skip는 통과가 아니며 필요한 환경이 없어 수행하지 않은 시험임.

핵심 코드 위치:

- `aether/parametric.py`: 차원 검증 AST evaluator와 도형 rebuild.
- `aether/gui/engineering.py`: 변수·치수·study·진단·CAD GUI 명령.
- `aether/gui/static/engineering.js`: 설계 workflow 대화상자와 비교 그래프.
- `aether/diagnostics.py`: 모델 사전 검사 및 지원 기능 상태.
- `aether/geometry/export.py`: 실패 시 기존 파일을 보호하는 CAD 내보내기.
- `aether/gui/measurement.py`: 선분/점 측정과 primitive 물성.
- `aether/fem/control.py`, `driver.py`, `adaptive.py`: 단계별 취소 전달.
- `tests/test_engineering_170.py`: 변수·파일·실 FEM·HTTP 회귀시험.

실행 결과 숫자는 최종 동봉 `test-results-1.7.0.xml` 및 다음 검증 요약을 기준으로 함.

### 이 배포본의 실행 결과

- 전체 pytest: **317 passed / 118 skipped / 0 failed**, 8.89초.
- 새 engineering 회귀시험: 42개 통과, OCC 전용 1개 skip.
- Python compileall, app.js와 engineering.js의 Node 구문 검사 통과.
- HTTP 프로젝트 생성·변수 변경·저장·재열기·치수 확인 통과.
- WR-90 10GHz 실제 FEM: 아래 세 조건 모두 반사계수 크기 <0.001, S21 크기 오차 <0.0002, 수동성·상호성 검사 통과.

| 요소 차수 | 최대 요소 크기 | Tetrahedra | 해석식 대비 S21 위상 오차 |
|---|---:|---:|---:|
| 1 | 4.0mm | 540 | 0.273757° |
| 1 | 2.5mm | 2,400 | 0.157496° |
| 2 | 5.0mm | 360 | 0.109167° |

총 skip 수에는 OCC 필요 시험과 browser 시험 모듈이 포함됨. 환경에 따라 module-level skip의 집계가 달라지므로 과거 버전과 skip 숫자만 직접 비교하면 안 됨. 브라우저 실행 시도는 로컬 URL 접근이 차단되어 이번 버전의 실제 클릭·렌더 검증을 완료하지 못했음. 위 숫자는 이 도파관 예제에서만 성립하며 임의 RF 구조의 오차 상한이 아님.
