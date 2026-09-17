사진관리 V2

핵심 원칙
- 원본은 삭제/이동하지 않고 정리본 폴더로 복사합니다.
- YYYY\\MM 구조로 정리합니다.
- 촬영 메타데이터를 최우선으로 사용합니다.
- 메타데이터가 없을 때 파일명 날짜, 마지막으로 파일 수정일을 사용합니다.
- SHA-256으로 완전히 동일한 파일을 중복 판정합니다.
- 결과를 사진정리_결과.csv로 저장합니다.

권장 사용법
1. 먼저 사진/동영상 20~30개를 별도 테스트 원본 폴더에 복사합니다.
2. V2에서 테스트 원본 폴더와 빈 테스트 결과 폴더를 선택합니다.
3. 실행 후 YYYY\\MM 폴더와 사진정리_결과.csv의 '촬영일' 및 '날짜판정방식'을 확인합니다.
4. 날짜가 맞는 것을 확인한 뒤 전체 원본에 실행합니다.

Windows EXE 빌드
- photo_organizer_v2.py, requirements_v2.txt, build-windows-v2.yml을 GitHub 저장소에 넣습니다.
- build-windows-v2.yml은 .github/workflows/build-windows-v2.yml 위치에 둡니다.
- GitHub Actions에서 Build Photo Organizer V2 -> Run workflow 실행.
- Artifacts에서 사진관리-V2-Windows-EXE를 내려받습니다.
