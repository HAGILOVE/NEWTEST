# 1.7.1 가져오기 오류 수정

## 확인된 원인

첨부된 로그의 STEP 파일은 OCC가 이미 `3 solid(s), 24 surface(s)`로 읽었음. 그 뒤 GUI가 각 부품 이름을 등록하는 단계에서 `_clean_part_name`을 호출하지만, 1.7.0에 해당 함수가 누락되어 실패했음. 이는 배포 코드의 결함임. 함수를 복원하고 한국어·중복 이름·빈 CAD 라벨을 처리하는 회귀 테스트를 추가했음. 실제 CAD 파일 읽기 없이도 이 분기를 검사하여 OCC 시험이 skip되어 같은 누락을 놓치지 않도록 했음.

DXF는 이전 구현이 이미 닫힘 표시가 있는 Polyline/Circle/Solid만 면으로 받아들였음. 개별 LINE/ARC로 이루어진 외곽, INSERT 블록, SPLINE/ELLIPSE를 제대로 처리하지 못했음. 또한 sheet만 있는 모델은 viewport fit 범위를 solids에서만 계산하므로, 불러왔어도 화면에서 찾기 어려운 문제가 있었음.

HFSS의 실제 오류 문구·원본 파일은 아직 제공되지 않았음. 따라서 해당 파일의 실패 원인을 확정하거나 해결됐다고 보장하지 않음. 코드 점검으로 확인한 UTF-16 BOM 디코딩과 AEDTZ 하위 폴더의 CAD 상대 경로 처리를 보완했음.

## 설치

1. 실행 중인 구버전 터미널/서버를 종료함.
2. 이번 ZIP을 **새 폴더**에 압축 해제함.
3. `SETUP_WINDOWS.cmd`를 실행함. 이번 버전은 추가 의존성 **ezdxf**를 설치해야 함.
4. 설치 성공 후 `START_WINDOWS.cmd` 실행.
5. 앱 상단/환경 검사에서 버전 **1.7.1**인지 확인함. 예전 브라우저 탭은 닫고 새로 열린 탭을 사용함.

원본 프로젝트와 CAD는 별도로 보관해야 함. 설치 파일을 옮기지 않은 채 예전 `.venv`에서 실행하면 수정 전 코드가 실행될 수 있음.

## 파일별 사용 방법

| 파일 | 메뉴 | 이번 처리 |
|---|---|---|
| HFSS `.aedt`, `.aedtz` | File → Open Project | 지원하는 design/geometry 항목 변환, UTF-16 BOM 및 nested archive CAD 경로 보완 |
| STEP/STP·IGES·BREP | Draw/Modeler → Import CAD | 복수 body 이름 등록 오류 수정. OCC 필요 |
| 닫힌 DXF 외곽 | Import CAD | 같은 layer의 연결된 LINE/ARC를 loop로 결합. OCC가 있으면 sheet 생성 |
| 열린 DXF 선 | Import CAD | 주황색 Reference 객체로 표시·이동·측정·저장. FEM에는 포함하지 않음 |
| 블록·곡선 DXF | Import CAD | ezdxf로 INSERT 분해, SPLINE/ELLIPSE/OCS 경로를 좌표로 변환 |

폐곡선 연결은 SI 기준 1e-7m 이내의 endpoint를 대상으로 하며, layer가 같고 연결 방향에 모호함이 없을 때만 수행함. 분기점·큰 틈을 임의로 닫지 않음. 열린 선은 두께·재료가 있는 도체가 아니므로, EM 해석에 쓸 경우 소스 CAD에서 닫힌 면을 만든 뒤 다시 가져와야 함.

곡선은 기본 1µm chord tolerance로 평탄화한 선분을 사용함. 면 생성 가능한 평면 closed contour를 대상으로 하며 임의 비평면 DXF를 volume으로 변환하지 않음. 텍스트·치수 기호·HATCH 등 지원 대상 밖의 엔티티는 Message Manager에 집계 경고를 표시함. 도면의 모델공간을 읽으며 paperspace 도면 레이아웃 자체를 복제하는 기능은 아님.

OCC가 없는 환경에서는 닫힌 DXF도 Reference로 표시함. 정상적인 해석용 sheet로 만들어졌다고 표시하지 않음. CAD surface export의 전체 범위에서는 Reference를 제외하며, Reference만 명시 선택해 내보내려 하면 원인과 대안을 알려줌.

## 저장과 화면 맞춤

DXF Reference는 원본 파일이 없어도 `.aedt/.aedtz` 저장·재열기 후 유지됨. 이동·회전·배율과 Undo/Redo를 지원함. 참조 선은 shaded 모드에서도 보이며, 2D-only 모델의 viewport fit에 실제 좌표 범위를 사용함. 열린 선의 선택은 프로젝트 트리 또는 Edge 모드를 사용함. 면이 아니므로 surface 클릭/face sweep 대상이 아님.

이전 닫힌 DXF importer는 중첩된 외곽을 구멍으로 처리함. 같은 위치의 여러 layer가 별도 물리 재료를 뜻하는 PCB 도면이라면 layer별로 분리한 DXF로 가져와야 함. PCB stackup을 자동 추론하는 기능은 아님.

## 재현용 파일

- `examples/import_checks/closed_from_lines.dxf`: 개별 LINE 네 개 → 20×10mm 폐곡선.
- `examples/import_checks/open_reference.dxf`: 열린 경로 → Reference 표시.
- `examples/import_checks/block_insert.dxf`: 회전된 INSERT 블록.

## 검증과 한계

전체 시험 결과는 `test-results-1.7.1.xml`에 포함함. 새 테스트는 assembly 등록, 중복/한글 이름, LINE/ARC 폐곡선, 열린 경로·분기점, 참조 도면 저장·재열기, INSERT 변환, SPLINE/ELLIPSE/OCS, UTF-16, 중첩 AEDTZ를 검증함.

STEP 실제 생성→3개 body 가져오기→render buffer→저장→원본 삭제 후 재열기 시험도 추가했지만, 현재 검증 환경에 `libGLU.so.1`이 없어 OCC 관련 시험은 실행하지 못했음. assembly 등록 회귀시험의 CAD probe는 모의 데이터이며, 실제 STEP 엔진 검증을 대체하지 않음. Windows와 WebGL 실제 화면 조작 역시 이번 환경에서 검증하지 못했음.

HFSS의 암호화/미지원 native history, Parasolid/ACIS 본체는 이 importer가 모두 지원하지 않음. `.hfss` 구형 형식은 Ansys에서 `.aedt`로 변환해야 할 수 있음. UTF-16 및 경로 시험이 통과했다고 임의 HFSS 파일 호환이 입증된 것은 아님.

**남은 실제 파일 검증에 필요한 자료:** 실패한 HFSS 프로젝트와 `Tx_Antenna_ver2.stp`, `meta_e96_02.dxf` 원본. 기밀 구조라면 같은 오류가 나는 최소 모델로 축소하여 제공할 수 있음. 해당 파일은 아직 제공받지 않았으므로 파일별 해결 여부는 미확정임.

개발 환경 재현:

```powershell
.venv\Scripts\python -m pip install -e ".[mesh,dev]"
.venv\Scripts\python -m pytest tests/test_import_171.py -q
.venv\Scripts\python -m pytest --junitxml=validation-tests.xml
```

DXF 확장 구현 참고: [ezdxf recursive decomposition](https://ezdxf.readthedocs.io/en/stable/disassemble.html), [Path 변환](https://ezdxf.readthedocs.io/en/stable/path.html).

DXF 단위 코드 8/9/21의 잘못된 매핑도 수정했음: Microinch / Mil / US survey foot를 구분함.

최종 검증: **334 passed / 118 skipped / 0 failed**. Python compileall, app.js/gl.js Node 구문 검사, pyflakes undefined-name 검사 통과. 전체 skip는 OCC·browser 등 환경 의존 항목이며 통과로 계산하지 않음.
