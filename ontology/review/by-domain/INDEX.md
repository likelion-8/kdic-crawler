# 6대 업무영역 Ontology 검토 인덱스

> 이 문서는 사람 검토를 분담하기 위한 생성물입니다. 승인 결정의 원본은 `../canonical-ontology-decisions.json`이며,
> 패킷의 체크 표시는 자동 승인·런타임 반영을 일으키지 않습니다.

## 검토 순서

1. 자신의 업무영역 패킷에서 엔터티와 핵심 사실의 원문·해시·범위를 검토합니다.
2. 결정은 `canonical-ontology-decisions.json`에 `approved`·`rejected`·`needs_changes`로 기록합니다.
3. 보강 후보는 이 패킷에서만 검토하며, 승인 후에도 별도 core fact 변경과 재검증이 필요합니다.
4. 생성물을 다시 만들고 release validator가 통과하는지 확인합니다.

| 업무영역 | 공식 문서 | 엔터티 결정 | 핵심 사실 결정 | 보강 후보 | 패킷 |
|---|---:|---:|---:|---:|---|
| 은닉재산 신고 | 4 | 3 | 2 | 0 | [은닉재산 신고](concealed_assets_report.md) |
| 채무조정 안내 | 8 | 5 | 4 | 0 | [채무조정 안내](debt_adjustment.md) |
| 예금보험금 안내 | 4 | 4 | 0 | 3 | [예금보험금 안내](deposit_insurance_payment.md) |
| 예금자보호제도 | 17 | 12 | 2 | 0 | [예금자보호제도](deposit_protection.md) |
| 착오송금 반환 신청 | 15 | 11 | 7 | 0 | [착오송금 반환 신청](mistaken_remittance_return.md) |
| 고객 미수령금 신청 | 10 | 10 | 0 | 3 | [고객 미수령금 신청](unclaimed_funds.md) |
