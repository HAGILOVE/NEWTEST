# HFSS 100 Tips (+40) — 적용 현황

"HFSS 100 Tips + 40 Tips"(v14 기준) 목차의 항목별로, 이 도구에 **무엇이 어디에 있는지**를 적음. 구현하지 않은 것은 이유와 함께 그대로 적음.

| # | 팁 | 상태 | 위치 / 비고 |
|---|---|---|---|
| 1 | CAD 모델 불러오기 | 기존 | File ▸ Import CAD (STEP/IGES/STL/DXF, 단위 검사, Heal 옵션) |
| 2 | 선택 모드 (by Area) | **신규** | Ctrl+드래그 / Box select. **왼→오: 걸친 개체까지, 오→왼: 완전히 포함된 개체만** (HFSS와 동일). Edit ▸ Select by Area Filter… (이름 `*` 패턴 포함/제외, 재질, Solid/Sheet/Line, 앞쪽 개체만) |
| 3 | Move Face (along normal) | 기존 | Modeler ▸ Move Faces… |
| 4 | Move Edge | **신규** | 평면 폴리곤/사각형의 모서리를 면 안에서 이동(+ 바깥, − 안쪽), 이웃 모서리가 따라 늘고 줄어듦. 곡면·솔리드 모서리는 미지원 |
| 5 | 단축키 만들기 | **신규** | Tools ▸ Keyboard Shortcuts… (메뉴의 모든 명령, 내보내기/가져오기) |
| 6 | 라인으로 패턴 만들기 | **신규** | Modeler ▸ Line Pattern… : 라인 → 폭이 있는 트레이스(면) / 직사각 단면 막대 / 원형 와이어 |
| 7 | Sweep around Axis | **신규** | Modeler ▸ Sweep Around Axis… (축 X/Y/Z, 점, 각도) |
| 8 | Sweep along Vector | **신규** | Modeler ▸ Sweep Along Vector… |
| 9 | Sweep along Path | **신규** | Modeler ▸ Sweep Along Path… 완만한 경로(헬릭스, 스파이럴)는 하나의 매끈한 sweep, 급한 꺾임은 직선 막대 + (원형이면) 구 이음. 단면은 경로 시작점에 직각으로 자동 정렬 |
| 10–13 | Equation Based Curve (타원, 비발디, 헬릭스, 스파이럴) | **신규** | Modeler ▸ Equation Based Curve… (x(_t), y(_t), z(_t), 변수, 점 수). 타원/헬릭스/스파이럴 프리셋. 비발디: 곡선 + Cover Lines + Mirror Copy 조합 |
| 14 | Split | **신규** | Modeler ▸ Split… (XY/YZ/ZX, 작업 CS 기준 위치, Positive / Negative / Both) |
| 15–17 | Duplicate (Along Line / Around Axis / Mirror) | 기존 + **신규** | 대화상자(Duplicate…) 외에 **두 점 클릭**으로: Copy & Move(개수 지정), Mirror, Mirror Copy. Paste & Move(Ctrl+Shift+V) |
| 18 | Mesher 선택 | 해당 없음 | 메셔가 하나(gmsh/OCC) |
| 19 | Import Mesh | 미구현 | 이전 해석의 최종 메시를 초기 메시로 쓰는 기능은 없음 |
| 20 | Mixed Order | 일부 | 1차/2차는 있음, Mixed(자동 혼합)는 없음 |
| 21 | Lumped port de-embedding | 미구현 | Wave 포트 de-embed 거리는 있음 |
| 22 | 개체 복사 시 경계/메시 연산도 복사 | **신규** | Duplicate / Paste / Copy & Move 가 기본으로 해당 개체의 경계조건, 포트(적분선·방향 포함), 메시 연산을 복사 (옵션으로 끔). 이동·회전·대칭·크기 변경 시에도 **따라 움직임** |
| 23 | DC Thickness | 해당 없음 | |
| 24 | Expression Cache | 일부 | Results ▸ Output Variables / Expression Plot: S, Y, Z, Freq 의 식(`1e9*im(Z(1,1))/2/pi/Freq`). **수렴 조건으로는 쓰지 않음** |
| 25 | Iterative Solve | 기존 | Tools ▸ Solver and Mesh Controls (직접/반복) |
| 26 | Dependent Solve Setup | 미구현 | |
| 27 | Simulation Queue | 미구현 | 해석은 한 번에 하나 |
| 28 | Material Override | 미구현 | |
| 29 | Radiated Field Overlay | 기존 | 3D Radiation Pattern + 모델/플롯 투명도 |
| 30 | Line 상 Field Plot | **신규** | Results ▸ Field on Line… (두 점 입력 또는 클릭, E/H, |V| 또는 성분, 특정 위상, 주파수, 여기) |
| 31 | 특정 단면 Field Plot | 기존 | Field on Cut Plane (X/Y/Z 평면) |
| 32 | Infinite Sphere | 기존 | Far Field Radiation Pattern (θ, φ 스텝). 사용자 좌표계 지정은 없음 |
| 33 | Custom Radiation Surface | 미구현 | |
| 34 | Radiation Surface 매뉴얼 메시 | 기존 | Add Mesh Operation (면 선택) |
| 35–40 | Remote / HPC / DSO | 해당 없음 | |

## 함께 고친 것
- **3D 회전이 일정 각도에서 멈추던 문제**: 상하 회전이 ±89°로 제한되어 있었음. 이제 극점을 넘어 계속 회전(뒤집힌 상태에서도 좌우 드래그가 손 방향과 일치). 내보낸 three.js 뷰어도 동일.
- **three.js(및 모든 파일) 저장이 조용히 취소되던 문제**: "파일이 이미 있습니다. 바꿀까요?"를 브라우저 내장 `confirm()`으로 물었는데, 내장 웹뷰 등에서는 이 창이 막혀 자동으로 "아니오"가 되었음. 앱 안의 대화상자로 바꿈(`prompt()`도 동일).
- **좌측 속성 패널**: 이름, 값, 주파수 범위 등 바꿀 수 있는 것은 입력란으로 편집 (Sweep 전체 필드, Setup 필드, 경계(RLC/임피던스/도전율), 포트(임피던스/모드/de-embed/Renormalize), 메시 연산, 프리미티브 치수, 프로젝트/디자인 이름, 모델 단위). 잘못된 값은 거부되고 이전 값이 복원됨.
- Revolve로 만든 형상을 저장했다 열면 각도가 틀리던 문제(도/라디안 혼동), 원(Circle) 시트가 `.warp`에 저장되지 않던 문제.
