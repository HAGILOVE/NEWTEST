# Aether EM 1.6.1 수정본 — 사용 및 검증 안내

이 배포본은 첨부된 1.6.0 소스를 수정한 개발용 패치이다. Ansys HFSS와 동등한 기능·정확도·파일 호환성을 인증한 상용 제품이 아니다. FEM 엔진을 교체하거나 해석 결과를 임의로 보정하지 않았다.

## 1. Windows 실행

1. ZIP을 **모두 압축 해제**한다. 압축 폴더 안에서 직접 실행하지 않는다.
2. Python 3.12가 설치된 Windows에서 `START_WINDOWS.cmd`를 실행한다.
3. 첫 실행은 프로젝트 폴더의 `.venv`를 만들고 NumPy, SciPy, gmsh와 이 소스를 설치한다. 이 단계는 인터넷 연결이 필요하다.
4. 설치가 끝나면 CAD 커널을 검사하고 로컬 웹 작업창을 연다. 터미널을 닫으면 서버가 종료된다.
5. 의존성 설치가 실패했거나 수정본을 같은 폴더에 덮어썼다면 `SETUP_WINDOWS.cmd`를 실행한다. 설치 성공 후 `START_WINDOWS.cmd`를 다시 실행한다.
6. 환경만 검사하려면 `CHECK_WINDOWS.cmd`를 실행한다. 설치 패키지를 ZIP에 포함한 오프라인 배포본은 아니다.

터미널 직접 실행: `py -3.12 run.py`

기존 가상환경을 수동 관리하는 개발자는 해당 환경에서 `python -m pip install -e ".[mesh]"` 후 `python -m aether.cli gui`를 실행할 수 있다. Linux의 gmsh는 별도의 시스템 OpenGL/GLU 라이브러리도 필요하다. Windows 실행은 이 검증 환경에서 직접 시험하지 못했다.

## 2. 불러오기와 저장

| 작업 | 사용 방법과 의미 |
|---|---|
| 프로젝트 열기 | File → Open Project 또는 Ctrl+O. `.aedt`, `.aedtz` 지원. 지원 가능한 Design이 없는 파일은 거부하고 현재 프로젝트 유지 |
| CAD 불러오기 | Modeler/Draw → Import. STEP/STP, IGES/IGS, BREP, STL/OBJ, DXF는 기존 importer 사용. 네이티브 CAD는 gmsh/OCC 필요 |
| CAD 크기 확인 | Import의 단위와 표시된 크기를 확인하고, 불러온 객체 선택 후 Measure에서 XYZ 크기를 검토 |
| CAD 소스 교체 | Replace CAD Source에서 파일과 단위를 다시 선택. 기존 이동/회전 이력 유지 |
| 일반 저장 | Ctrl+S. 형상, 지원되는 재료·경계·포트·설정·Sweep 및 로컬 mesh operation을 저장 |
| 다른 이름으로 저장 | File → Save Project As 또는 Ctrl+Shift+S |
| 다른 PC로 전달 | `.aedtz`로 저장하면 CAD 부속 파일도 압축 파일에 동봉. `.aedt`는 동명의 `.cad` 폴더를 함께 전달해야 함 |
| 이전 저장 복구 | 기존 파일을 덮어쓰기 전 `<파일명>.bak` 보관. 복사본을 원래 확장자 `.aedt` 또는 `.aedtz`로 복구하여 열 것 |

저장 성공은 임시 파일 작성과 최종 교체가 완료된 뒤에만 표시한다. 저장이 실패하면 기존 프로젝트 파일을 유지하며 수정 표시도 유지한다. 소스가 없거나 CAD 사본을 보관할 수 없으면 저장을 실패 처리한다. 같은 `part.step` 이름을 가진 서로 다른 파일은 내용 기반 이름으로 구분된다. `.cad` 폴더에는 이전 저장의 CAD 파일도 남을 수 있으므로 최근 백업 복구에 필요한 파일을 임의로 지우지 말 것.

다른 프로젝트를 열 때 Undo/Redo, 클립보드와 선택을 초기화한다. 변경사항이 있으면 새 프로젝트·템플릿·다른 파일 열기 전에 폐기 확인을 표시한다. 브라우저 닫기/새로고침 보호는 브라우저가 제공하는 확인 기능이며, 자동 저장이나 강제 종료 복구 기능은 아니다.

**Native HFSS 프로젝트:** 지원 가능한 항목을 변환하는 importer이다. GUI 저장은 지원되는 모델·경계·해석 설정 브랜치를 재작성한다. 그 내부의 미지원 native history, 설정 및 참조가 보존된다고 보장할 수 없다. 실제 HFSS 원본은 보관하고 Save As로 작업할 것. 명시적 Python writer `mode='update'`는 기존의 제한적인 설정 갱신 기능으로 남아 있으며, GUI의 일반 편집 저장과 다르다.

## 3. 치수 측정

Edit → **Measure / Dimensions**, Modeler ribbon → **Measure**, 또는 **M** 키를 사용한다.

| 모드 | 결과 | 정확도 범위 |
|---|---|---|
| 선택 객체 | XYZ 바운딩박스, 중심, 대각선, 두 객체 바운딩박스 간격 | Symbolic bounds 기반의 외접 범위. 곡면·회전·Boolean의 실제 표면 최소 간격과 다를 수 있음 |
| 선택 모서리 | 길이 합계, 두 선분 사이 최소 거리, 두 선분 방향각 | 선택된 직선분의 최소거리는 해석적 계산. 곡선 CAD edge는 테셀레이션 선분일 수 있음 |
| 선택 면 | 면적 합계, 범위, 두 면 간격, 평행면 간 평면거리 | 면적은 테셀레이션 기반. 면 간격은 샘플링 근사이며 정밀 CAD clearance가 아님 |
| Two-point distance | 3D 거리와 부호 있는 ΔX·ΔY·ΔZ | 입력 좌표 기반 계산 |
| Three-point angle | A–B–C 각도, B가 꼭짓점 | 입력 좌표 기반, 0~180° |
| Circle through three points | 중심, 반지름, 직경, 원주 | 원주 위의 세 좌표 기반. 공선점·중복점은 거부 |

- 단위: m / cm / mm / um / mil / in. 좌표 칸의 숫자는 선택 단위를 사용하고 `2.5mm`, `1in` 같은 명시 단위도 허용한다.
- 선택 모드의 표시는 모델 단위를 사용한다. Coordinate units 선택은 수동 좌표 측정에 적용된다.
- 기존 edge/face 선택은 **Use picked endpoints / face points**로 좌표 칸에 가져올 수 있다. Face point는 원의 중심이나 원주점을 자동 추론한 값이 아니다.
- **Edit → Measure by clicking**에서 거리·각도·원 측정용 2점/3점을 클릭할 수 있다. 툴바에도 2점 측정 버튼을 추가했다. 화면상의 인접 edge endpoint를 12px 이내에서 선택하며, 그 외에는 화면에 표시된 surface 또는 작업평면을 사용한다. Esc로 취소한다.
- 화면 클릭점은 표시용 geometry에 기반하므로 원본 BREP vertex 정확도를 보증하지 않는다. 설계에 사용할 정밀 수치는 명시 좌표로 재확인할 것.
- **Calculate**로 계산하고 **Export CSV**로 측정 결과를 다운로드한다. CSV의 수치 필드는 SI 길이 m, 면적 m², 체적 m³, 각도 degree이며 Summary는 표시 단위를 사용한다.

## 4. 편집과 Resize

객체 모드(O)에서 한 객체를 선택 → **Edit → Resize to Dimensions** 또는 Modeler → Resize.

X/Y/Z 목표 크기와 기준점(중심 또는 최소 XYZ 모서리)을 입력한다. 이 기능은 모델의 바운딩박스 기준으로 scaling한다. XYZ 비율이 다르면 원이 타원이 될 수 있고, 곡면이나 Boolean의 바운딩박스는 근사 범위일 수 있다. 두께 0인 sheet를 solid로 만들려면 Sweep Face를 사용해야 한다.

기존 Move·Rotate·Mirror·Scale·Duplicate·Boolean은 유지했다. 이번 패치에서 확인한 개선은 다음과 같다.

- 편집 도중 예외가 발생하면 현재 Design 스냅샷, 선택, dirty 표시, Undo/Redo를 복구한다.
- Cut도 Undo가 가능하고, 편집 성공 시 이전 해석 결과를 무효화한다.
- 해석 진행 중 형상 편집과 프로젝트 전환을 차단한다.
- 객체 rename 시 mesh operation 대상 이름을 갱신하고, 대상 객체가 모두 삭제된 mesh operation은 경고와 함께 제거한다. Undo로 함께 복구한다.
- geometry 갱신 시 이전 face/edge 선택과 측정 표시를 정리한다.
- 실패한 대화상자는 입력을 유지하며, 오류 상태가 즉시 Ready로 덮이지 않도록 수정했다.
- 스크립트가 수행한 외부 파일 작업이나 임의 전역 상태까지 Undo로 복구하는 것은 아니다.

## 5. 개발자 검증

검증 환경: Linux, Python 3.12. 첨부 원본의 초기 테스트: 253 passed / 158 skipped.

최종 검증: **275 passed / 162 skipped**, 실패 없음. 상세 원본은 `docs/test-results-1.6.1.xml`에 포함한다. Python compileall 및 `node --check aether/gui/static/app.js`도 통과했다.

추가한 backend 회귀 테스트 22개는 다음을 검증한다.

- 재열기 → 이동/추가/삭제 → 재저장 → 다시 열기
- 새 Design 추가 후 재저장
- 프로젝트 간 Undo 및 클립보드 초기화
- 저장 교체 실패 시 기존 바이트와 dirty 표시 유지
- 동일 파일명 CAD 두 개 보관 및 원본/sidecar 삭제 후 이동한 `.aedtz`에서 payload 복구
- 부분 편집 실패 롤백과 Redo 유지, Cut/Undo, 해석 중 편집 차단
- 목표 치수 Resize/Undo
- 교차·평행·퇴화·이격 선분의 거리, 단위 변환, XYZ 차이, 각도·원 계산과 잘못된 입력 거부
- 단위, mesh operation, 최소 adaptive pass, basis order, 비균일 sweep points, SaveFields 재저장
- 객체 rename/delete 후 mesh 참조 유효성

건너뛴 테스트를 성공으로 간주하지 않는다. gmsh Python 패키지는 있으나 `libGLU.so.1`이 없어 OCC 기반 CAD·meshing·일부 물리 테스트가 실행되지 않았다. Chromium도 없고 다운로드가 시간 초과되어 브라우저 테스트가 실행되지 않았다. 새 UI 테스트 4개는 `tests/test_release_browser.py`에 포함했으나 이 환경에서 통과를 확인하지 못했다.

Windows 검증 명령(개발용):

```
.venv\Scripts\python -m pip install pytest playwright
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python -m pytest tests -q
```

CAD 포함 archive 회귀 테스트의 payload 보존은 검증했지만, 이동한 실제 STEP의 BREP 재구성과 렌더링까지 검증한 것은 아니다. 기존 네이티브 CAD 테스트는 유지했다.

## 6. 아직 완료되지 않은 항목

- Windows native file dialog, 새 버튼/단축키/화면 클릭의 브라우저 실제 조작 검증
- 실제 사용자의 STEP/DXF/HFSS 파일 모음에 대한 불러오기→편집→저장→재열기 검수
- HFSS와의 mesh convergence / S-parameter / field / port normalization 상관 검증
- arbitrary CAD surface의 정확한 최소 거리, 원통면 자동 직경 측정, 치수 구속 기반 parametric sketch solver
- HFSS 전체 기능 및 native AEDT 전체 데이터 호환
- 기존 writer의 주파수 의존 재료 모델에 대한 완전한 round-trip 보존 검증

이 범위가 해결되기 전에는 '모든 기능 완벽 동작' 또는 'HFSS와 동등한 상용 해석기'라고 표시해서는 안 된다.
