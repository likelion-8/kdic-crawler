# KDIC Ontology Concept Review Queue

Generated from the v1 metadata map. Every item is `proposed`; it is not a runtime query term, a fact, or a production retrieval filter.

## Scope and review rules

1. Review from the linked official pages only. Do not use `data/testset` or its results to choose labels or synonyms.
2. Accept a label only when it represents a stable KDIC domain concept, task, rule, or status. Reject navigation-only and overly broad labels.
3. Record a canonical label, a concept kind, and any synonyms separately. Synonyms require an official-page citation.
4. Keep `page_id` and `content_sha256` as the evidence pointer. If the corpus hash changes, review the item again.
5. Only entries explicitly marked `approved` in a future curated source may be evaluated as retrieval hints; no automatic promotion is allowed.

Suggested concept kinds: `Service`, `Eligibility`, `Procedure`, `RequiredDocument`, `Deadline`, `MonetaryRule`, `Organization`, `Policy`, `Status`, `ContactChannel`.

## Queue

- Concepts: 95
- Source documents: 58
- Priority: P1 = used by 3+ documents; P2 = used by 2 documents; P3 = one document.

## P1-001 · `concept:c_0c5aafb82cf87be3`

- Metadata label: `미수령금 통합조회/신청`
- Evidence usage: 8 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_fndt` — 파산재단현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtPsta.do
    - content_sha256: `4ac0da576f6f00b5f460568f03a99ed4ce6a421060f33dca66adfaddd1d15946`
  - `uc_bkrp_mng` — 파산재단관리
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtMng.do
    - content_sha256: `ffb3d70566ced75adac265f8a23d0f9c9ea47178ba2c4bd3e413e8bd86eb5188`
  - `uc_bkrp_spcl_ast` — 특별자산현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstPsta.do
    - content_sha256: `3f959b62d5de6190d49af788f352f16f0b8ae76684dbf59d2fe266e8b7416dbc`
  - `uc_bkrp_spcl_mng` — 특별자산관리체계
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstMngStm.do
    - content_sha256: `3a0860d1b3bf0214ea9a36dfec58a05c1005a3aa083c8caf0d0bebb3a204d753`
  - `uc_bkrp_trst_mng` — 신탁부동산관리체계
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestMngStm.do
    - content_sha256: `131d34d20ced7ed553141591e715e3c65fe5572f11a75fe70afff7abf17aa6d3`
  - `uc_bkrp_trst_psta` — 신탁부동산현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestPsta.do
    - content_sha256: `bf33dc193dfe488d6685a904bd1bc8b49c8f99be3822a77fddbcfcfb28ee6a8a`
  - `uc_gudn` — 고객미수령금
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do
    - content_sha256: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`
  - `uc_hrpe_hist` — 상속인 금융거래조회
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystHrpeHistInq/selectScrn.do
    - content_sha256: `50285fcc51505cc304aaec963e33d93981983b989497ca989d8eb9f22b027e61`

## P1-002 · `concept:c_c5b5a0a24f3477f8`

- Metadata label: `파산금융회사 정보 검색`
- Evidence usage: 6 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_fndt` — 파산재단현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtPsta.do
    - content_sha256: `4ac0da576f6f00b5f460568f03a99ed4ce6a421060f33dca66adfaddd1d15946`
  - `uc_bkrp_mng` — 파산재단관리
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtMng.do
    - content_sha256: `ffb3d70566ced75adac265f8a23d0f9c9ea47178ba2c4bd3e413e8bd86eb5188`
  - `uc_bkrp_spcl_ast` — 특별자산현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstPsta.do
    - content_sha256: `3f959b62d5de6190d49af788f352f16f0b8ae76684dbf59d2fe266e8b7416dbc`
  - `uc_bkrp_spcl_mng` — 특별자산관리체계
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstMngStm.do
    - content_sha256: `3a0860d1b3bf0214ea9a36dfec58a05c1005a3aa083c8caf0d0bebb3a204d753`
  - `uc_bkrp_trst_mng` — 신탁부동산관리체계
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestMngStm.do
    - content_sha256: `131d34d20ced7ed553141591e715e3c65fe5572f11a75fe70afff7abf17aa6d3`
  - `uc_bkrp_trst_psta` — 신탁부동산현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestPsta.do
    - content_sha256: `bf33dc193dfe488d6685a904bd1bc8b49c8f99be3822a77fddbcfcfb28ee6a8a`

## P1-003 · `concept:c_3c48ca055b59c51b`

- Metadata label: `보호대상`
- Evidence usage: 5 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_fnst` — 보호대상 금융회사 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSumr.do
    - content_sha256: `f9aefe8660a4ae5b77f5874c415d24703eeb43fa23a4238cf219d3c617c06747`
  - `dp_fnst_srch` — 보호대상금융회사검색
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSrch.do
    - content_sha256: `7bea25e25d0465ee97127aca6a748909a9abd48f86a3ab997414053d028f65f1`
  - `dp_prdct` — 보호대상 금융상품 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSumr.do
    - content_sha256: `8808cd72cd02c7be17125ad6b48a882635b8e77b846654dd914913374516d174`
  - `dp_prdct_srch` — 보호대상금융상품검색
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSrchList.do
    - content_sha256: `6571b6a932881acf42aa23bf2693284ae48d7ba3721a2459261e89b52f2184f5`
  - `dp_svbk_hist` — 저축은행변경이력
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystSvbkChgHstry.do
    - content_sha256: `f7883d0f99f2f432c3ffd4c4e93895df9ae78050f71b6a646f6b3a8d0afabf5c`

## P1-004 · `concept:c_21ec591f2025d4c5`

- Metadata label: `소개와 방법안내`
- Evidence usage: 4 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `mtrs_gvbk_proc` — 반환지원절차
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsGvbkSprtProc/selectScrn.do
    - content_sha256: `a4803ab34cf7189c914c53dc8dbb6637a33556b4e85b8d1f389906f121fe537f`
  - `mtrs_rel_law` — 관련법령 및 규정
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsRelLawoRgul/selectScrn.do
    - content_sha256: `46d7def4dfbe218f531ef6ce6e8484d763659eb50722e849f49f084d6ead9730`
  - `mtrs_stut_chc` — 상황선택
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsStutChc/selectScrn.do
    - content_sha256: `2b85e52da3cf42af3b46e2856b203a7a84395366dd7ec29bc6137536491bbedb`
  - `mtrs_vst_rcpt` — 방문접수안내
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsVstRcptGudn/selectScrn.do
    - content_sha256: `81cc3ded70380a222d38b27fe3823e22cab56f56f94de34fc5a2fec01f653807`

## P1-005 · `concept:c_3f293d28d1e34528`

- Metadata label: `표시·설명·확인 제도`
- Evidence usage: 4 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_gudn` — 표시·설명·확인 제도 안내
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtGudn/selectScrn.do
    - content_sha256: `dccd0b0bcc9c2becc411d6e87f3e70e1606885ba6d567986bf81e32ccb242e23`
  - `dp_gudn_data` — 안내자료 다운로드
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystDataDwnldList.do
    - content_sha256: `277bc8673d7e26f7c773524f321fdd3ceea6903ab7019980e37b7c3dcd36244d`
  - `dp_gudn_faq` — 표시·설명·확인 제도 관련 FAQ
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtSystFaq/selectScrn.do
    - content_sha256: `c05522f4f7b5b14e720c8059445f3fc6e75b62698f71fdb50aa028837d3b07c1`
  - `dp_logo` — 예금보호 로고 사용 안내
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLogoUseGudn/selectScrn.do
    - content_sha256: `b13558ea8d7751e0ce05b5495297e8e0052178c445171ce682a47c3552951609`

## P1-006 · `concept:c_dff04cca052051af`

- Metadata label: `금융회사`
- Evidence usage: 3 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_fnst` — 보호대상 금융회사 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSumr.do
    - content_sha256: `f9aefe8660a4ae5b77f5874c415d24703eeb43fa23a4238cf219d3c617c06747`
  - `dp_fnst_srch` — 보호대상금융회사검색
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSrch.do
    - content_sha256: `7bea25e25d0465ee97127aca6a748909a9abd48f86a3ab997414053d028f65f1`
  - `dp_svbk_hist` — 저축은행변경이력
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystSvbkChgHstry.do
    - content_sha256: `f7883d0f99f2f432c3ffd4c4e93895df9ae78050f71b6a646f6b3a8d0afabf5c`

## P1-007 · `concept:c_1e0253f62c754140`

- Metadata label: `미수령금통합신청`
- Evidence usage: 3 document(s); service(s): `고객 미수령금 신청`, `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_nramt` — 미수령금통합신청 FAQ (실제 내용은 예금보호)
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqNramtAply.do
    - content_sha256: `dfc822c1156e098bd93ff5c4b2908fcc3145625550828faa9f1e2cedaa893060`
  - `uc_itgr_aply` — 안내
    - URL: https://fins.kdic.or.kr/ua/aplygudn/NramtItgrAplyItrdMthdGudn/selectScrn.do
    - content_sha256: `c7fee2ab2ce3bd2ec489f51236ea07f0cb6d931496e75cbed1299466ba4f1898`
  - `uc_tel_qust` — 예금자 대상 전화문의 안내
    - URL: https://fins.kdic.or.kr/ua/aplygudn/DpstrTrgtTelQustGudn/selectScrn.do
    - content_sha256: `39d6f5311215c364f8533142690c38f74f315b04338d057b1a401abeb43e900f`

## P1-008 · `concept:c_6a91436ac7264d5d`

- Metadata label: `부보금융회사조사`
- Evidence usage: 3 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_itrd` — 부보금융회사조사 업무 소개
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaItrd/selectScrn.do
    - content_sha256: `9edde39f7b3f5537ecdae0df628602c25ea1691f536c82fc3a8b2d8ee0fd868a`
  - `dp_josa_law` — 부보금융회사조사 법적근거 및 관련규정
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaRgul/selectScrn.do
    - content_sha256: `0be73d35eb6e82335cf79e906a5b38a14ab0eaf5d2778e248f019881b6930353`
  - `dp_josa_objc` — 부보금융회사조사 소명 및 이의제기 신청
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaExplPrtsAplyGudn/selectScrn.do
    - content_sha256: `55199305c163c5f4fbd7c9e307ab0f28c897828356d40640b938501adbbb0187`

## P2-009 · `concept:c_dbc468a14b601d5d`

- Metadata label: `FAQ`
- Evidence usage: 2 document(s); service(s): `예금자보호제도`, `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_nramt` — 미수령금통합신청 FAQ (실제 내용은 예금보호)
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqNramtAply.do
    - content_sha256: `dfc822c1156e098bd93ff5c4b2908fcc3145625550828faa9f1e2cedaa893060`
  - `ha_faq_dclr` — 은닉재산신고 FAQ
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqCncmPrptDclr.do
    - content_sha256: `9e72acbd7c27d0e6d80d0fc0c2e41a7b0a4d295c4d3d9790ef5eb6b9aaad5039`

## P2-010 · `concept:c_dc015df639b9ffb5`

- Metadata label: `개요`
- Evidence usage: 2 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_fnst` — 보호대상 금융회사 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSumr.do
    - content_sha256: `f9aefe8660a4ae5b77f5874c415d24703eeb43fa23a4238cf219d3c617c06747`
  - `dp_prdct` — 보호대상 금융상품 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSumr.do
    - content_sha256: `8808cd72cd02c7be17125ad6b48a882635b8e77b846654dd914913374516d174`

## P2-011 · `concept:c_8497eb60b73b67fd`

- Metadata label: `고객센터`
- Evidence usage: 2 document(s); service(s): `예금자보호제도`, `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_nramt` — 미수령금통합신청 FAQ (실제 내용은 예금보호)
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqNramtAply.do
    - content_sha256: `dfc822c1156e098bd93ff5c4b2908fcc3145625550828faa9f1e2cedaa893060`
  - `ha_faq_dclr` — 은닉재산신고 FAQ
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqCncmPrptDclr.do
    - content_sha256: `9e72acbd7c27d0e6d80d0fc0c2e41a7b0a4d295c4d3d9790ef5eb6b9aaad5039`

## P2-012 · `concept:c_7173c92dada04b96`

- Metadata label: `금융상품`
- Evidence usage: 2 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_prdct` — 보호대상 금융상품 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSumr.do
    - content_sha256: `8808cd72cd02c7be17125ad6b48a882635b8e77b846654dd914913374516d174`
  - `dp_prdct_srch` — 보호대상금융상품검색
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSrchList.do
    - content_sha256: `6571b6a932881acf42aa23bf2693284ae48d7ba3721a2459261e89b52f2184f5`

## P2-013 · `concept:c_51f8fbdf3ff9e253`

- Metadata label: `소개와 신청방법 안내`
- Evidence usage: 2 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_itgr_aply` — 안내
    - URL: https://fins.kdic.or.kr/ua/aplygudn/NramtItgrAplyItrdMthdGudn/selectScrn.do
    - content_sha256: `c7fee2ab2ce3bd2ec489f51236ea07f0cb6d931496e75cbed1299466ba4f1898`
  - `uc_tel_qust` — 예금자 대상 전화문의 안내
    - URL: https://fins.kdic.or.kr/ua/aplygudn/DpstrTrgtTelQustGudn/selectScrn.do
    - content_sha256: `39d6f5311215c364f8533142690c38f74f315b04338d057b1a401abeb43e900f`

## P2-014 · `concept:c_5b20f0b6b9ebb5f9`

- Metadata label: `착오송금인`
- Evidence usage: 2 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_attention` — 착오송금인 유의사항
    - URL: https://fins.kdic.or.kr/ir/msdrpr/MsdrprAttnMttr/selectScrn.do
    - content_sha256: `963ad6c3ea313510e69065cb12dfc64f66102c94bf0c45cea0f27ac18f3f60c7`
  - `sender_qlfc_check` — 신청대상여부 확인 (자가진단)
    - URL: https://fins.kdic.or.kr/ir/msdrpr/selectAplyQlfcIdntyRslt.do
    - content_sha256: `c6364958af05b92718e2fdc11be7a6d69921aaf04eed20a3f7bb869499b11e05`

## P3-015 · `concept:c_01a5d76df6fbb2e7`

- Metadata label: `FAQ - 착오송금반환지원신청`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_msdr_apply` — FAQ - 착오송금반환지원신청
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqMsdrGvbkAply.do
    - content_sha256: `a55ff31bdc14e60875eb95132ca9cb599e437b8120257c949f9abc1d16966456`

## P3-016 · `concept:c_3d101c3f14e24f9f`

- Metadata label: `FAQ_TOP10`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_top10` — 고객센터 FAQ TOP 10
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqTop10.do
    - content_sha256: `34b2ec2438cd9e5f06301a9ecdaa56f6915339a8bdf7e8971bc7a9da28418db9`

## P3-017 · `concept:c_e7669145125672ed`

- Metadata label: `FAQ_반환지원신청`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_msdr_apply` — FAQ - 착오송금반환지원신청
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqMsdrGvbkAply.do
    - content_sha256: `a55ff31bdc14e60875eb95132ca9cb599e437b8120257c949f9abc1d16966456`

## P3-018 · `concept:c_bbcd9a329f749697`

- Metadata label: `KR&C 채무조정`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_kruc` — 채무조정
    - URL: https://www.kdic.or.kr/di/relsite/PbcrKrncLblarb/selectScrn.do
    - content_sha256: `12dfb1ce59d6d3fab50a7e8e4628cdf253f6ab7d36844933fe69302c430d6143`

## P3-019 · `concept:c_8510af5f765e4bb0`

- Metadata label: `개인회생`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_psn_rg` — 개인회생
    - URL: https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do
    - content_sha256: `9901d6f02393e4636842e0a032491c81b5740c3b4822176ea1da7ebba2fe4252`

## P3-020 · `concept:c_6320ddef25ed6d7d`

- Metadata label: `고객미수령금`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_gudn` — 고객미수령금
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do
    - content_sha256: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`

## P3-021 · `concept:c_02ee110020a6af4c`

- Metadata label: `고객센터 FAQ TOP 10`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_top10` — 고객센터 FAQ TOP 10
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqTop10.do
    - content_sha256: `34b2ec2438cd9e5f06301a9ecdaa56f6915339a8bdf7e8971bc7a9da28418db9`

## P3-022 · `concept:c_c591b3969a3df809`

- Metadata label: `관련법령 및 규정`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `mtrs_rel_law` — 관련법령 및 규정
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsRelLawoRgul/selectScrn.do
    - content_sha256: `46d7def4dfbe218f531ef6ce6e8484d763659eb50722e849f49f084d6ead9730`

## P3-023 · `concept:c_e9b60e5017283530`

- Metadata label: `구비서류_수취인`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `receiver_docs` — 구비서류안내 - 착오송금수취인
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MsdrAddrsePossDcmntGudn/selectScrn.do
    - content_sha256: `f9bed4bbb32986ec7a23a55ae61f3a48c11af5239510903822558a3df8968d37`

## P3-024 · `concept:c_f2b76b33d1b61a49`

- Metadata label: `구비서류_착오송금인`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_docs` — 구비서류안내 - 착오송금인
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MsdrprPossDcmntGudn/selectScrn.do
    - content_sha256: `5a480687efac403e42a51f832ccf877f1c7864290486bb4e5123caccb3577814`

## P3-025 · `concept:c_36df84cf8d685a1e`

- Metadata label: `구비서류안내 - 착오송금수취인`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `receiver_docs` — 구비서류안내 - 착오송금수취인
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MsdrAddrsePossDcmntGudn/selectScrn.do
    - content_sha256: `f9bed4bbb32986ec7a23a55ae61f3a48c11af5239510903822558a3df8968d37`

## P3-026 · `concept:c_604f66337c048cde`

- Metadata label: `구비서류안내 - 착오송금인`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_docs` — 구비서류안내 - 착오송금인
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MsdrprPossDcmntGudn/selectScrn.do
    - content_sha256: `5a480687efac403e42a51f832ccf877f1c7864290486bb4e5123caccb3577814`

## P3-027 · `concept:c_ca1c1facfc0730df`

- Metadata label: `금융부실관련자 불법행위신고`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_ilgl_intro` — 신고센터 소개
    - URL: https://www.kdic.or.kr/sp/sprtfund/SprtFndIvsfalUnrlIlglDclrGudn/selectScrn.do
    - content_sha256: `06f9fa77314a9075fadc91c9f878487b8579376bf58edbf0f09f7fcfb95cad70`

## P3-028 · `concept:c_578fa9f57bc44cce`

- Metadata label: `금융부실관련자 은닉재산신고`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_center` — 신고센터
    - URL: https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do
    - content_sha256: `dba66fb0b1581bf925c8cc2eff706e7efe2468c6ad22d9b6fd438d70e51cd799`

## P3-029 · `concept:c_d4949d1cefa5e1fd`

- Metadata label: `미수령금통합신청 FAQ (실제 내용은 예금보호)`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `faq_nramt` — 미수령금통합신청 FAQ (실제 내용은 예금보호)
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqNramtAply.do
    - content_sha256: `dfc822c1156e098bd93ff5c4b2908fcc3145625550828faa9f1e2cedaa893060`

## P3-030 · `concept:c_e1e0195c15458b84`

- Metadata label: `반환지원 신청하기`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_qlfc_check` — 신청대상여부 확인 (자가진단)
    - URL: https://fins.kdic.or.kr/ir/msdrpr/selectAplyQlfcIdntyRslt.do
    - content_sha256: `c6364958af05b92718e2fdc11be7a6d69921aaf04eed20a3f7bb869499b11e05`

## P3-031 · `concept:c_0b8eebe581a8a3d2`

- Metadata label: `반환지원절차`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `mtrs_gvbk_proc` — 반환지원절차
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsGvbkSprtProc/selectScrn.do
    - content_sha256: `a4803ab34cf7189c914c53dc8dbb6637a33556b4e85b8d1f389906f121fe537f`

## P3-032 · `concept:c_14b7e7c9a0048de6`

- Metadata label: `방문접수안내`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `mtrs_vst_rcpt` — 방문접수안내
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsVstRcptGudn/selectScrn.do
    - content_sha256: `81cc3ded70380a222d38b27fe3823e22cab56f56f94de34fc5a2fec01f653807`

## P3-033 · `concept:c_c9a28ddb4109e2e2`

- Metadata label: `법적근거 및 관련규정`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_law` — 부보금융회사조사 법적근거 및 관련규정
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaRgul/selectScrn.do
    - content_sha256: `0be73d35eb6e82335cf79e906a5b38a14ab0eaf5d2778e248f019881b6930353`

## P3-034 · `concept:c_7f853071bbe38720`

- Metadata label: `보험금 지급대상 금융회사`
- Evidence usage: 1 document(s); service(s): `예금보험금 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ms_trgt_fnst` — 보험금 지급대상 금융회사
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystBamtGiveTrgtFnst.do
    - content_sha256: `72cf381ebd633bb4bb10fabdcd982445d1635aa8dab726c2201c31621f74778d`

## P3-035 · `concept:c_432bb4bc988fe3b0`

- Metadata label: `보호대상 금융상품 개요`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_prdct` — 보호대상 금융상품 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSumr.do
    - content_sha256: `8808cd72cd02c7be17125ad6b48a882635b8e77b846654dd914913374516d174`

## P3-036 · `concept:c_294453a954cac30f`

- Metadata label: `보호대상 금융회사 개요`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_fnst` — 보호대상 금융회사 개요
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSumr.do
    - content_sha256: `f9aefe8660a4ae5b77f5874c415d24703eeb43fa23a4238cf219d3c617c06747`

## P3-037 · `concept:c_4b45f68eeb3692df`

- Metadata label: `보호대상금융상품검색`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_prdct_srch` — 보호대상금융상품검색
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSrchList.do
    - content_sha256: `6571b6a932881acf42aa23bf2693284ae48d7ba3721a2459261e89b52f2184f5`

## P3-038 · `concept:c_420449bdcc3ca2b7`

- Metadata label: `보호대상금융회사검색`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_fnst_srch` — 보호대상금융회사검색
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSrch.do
    - content_sha256: `7bea25e25d0465ee97127aca6a748909a9abd48f86a3ab997414053d028f65f1`

## P3-039 · `concept:c_6054401109e7869f`

- Metadata label: `보호한도`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_protlmts` — 보호한도
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLmts/selectScrn.do
    - content_sha256: `80ae7ac40cf6e94b0114f69461c164906920ea5fa0a1265c372a5a2ff7070637`

## P3-040 · `concept:c_26fbcc7c3750d410`

- Metadata label: `부보금융회사조사 법적근거 및 관련규정`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_law` — 부보금융회사조사 법적근거 및 관련규정
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaRgul/selectScrn.do
    - content_sha256: `0be73d35eb6e82335cf79e906a5b38a14ab0eaf5d2778e248f019881b6930353`

## P3-041 · `concept:c_c9b4d3c4b528c3d1`

- Metadata label: `부보금융회사조사 소명 및 이의제기 신청`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_objc` — 부보금융회사조사 소명 및 이의제기 신청
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaExplPrtsAplyGudn/selectScrn.do
    - content_sha256: `55199305c163c5f4fbd7c9e307ab0f28c897828356d40640b938501adbbb0187`

## P3-042 · `concept:c_adb79e3342c34c10`

- Metadata label: `부보금융회사조사 업무 소개`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_itrd` — 부보금융회사조사 업무 소개
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaItrd/selectScrn.do
    - content_sha256: `9edde39f7b3f5537ecdae0df628602c25ea1691f536c82fc3a8b2d8ee0fd868a`

## P3-043 · `concept:c_15efa1acd3ac5c8a`

- Metadata label: `부실책임조사`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_status_agree` — 부실책임조사 진행현황 조회 (개인정보 동의)
    - URL: https://www.kdic.or.kr/voc/userDataUsingAgree
    - content_sha256: `7a9070848f1a43399c08a0345c2e11d035efd82a3e85f6cc608181d86b7b865e`

## P3-044 · `concept:c_b2d903535dcbefff`

- Metadata label: `부실책임조사 진행현황 조회 (개인정보 동의)`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_status_agree` — 부실책임조사 진행현황 조회 (개인정보 동의)
    - URL: https://www.kdic.or.kr/voc/userDataUsingAgree
    - content_sha256: `7a9070848f1a43399c08a0345c2e11d035efd82a3e85f6cc608181d86b7b865e`

## P3-045 · `concept:c_ac01d1377dbeeb01`

- Metadata label: `부채증명원 및 금융거래정보신청`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_debt_cert` — 부채증명원/금융거래정보신청
    - URL: https://www.kdic.or.kr/sp/sprtfund/SprtFndDebtDlngAplyGudn/selectScrn.do
    - content_sha256: `b34de2685db8ddf35e4826afcbced17020682dafa0052f7752f6d7930ee3fb4a`

## P3-046 · `concept:c_e72556a476852b72`

- Metadata label: `부채증명원/금융거래정보신청`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_debt_cert` — 부채증명원/금융거래정보신청
    - URL: https://www.kdic.or.kr/sp/sprtfund/SprtFndDebtDlngAplyGudn/selectScrn.do
    - content_sha256: `b34de2685db8ddf35e4826afcbced17020682dafa0052f7752f6d7930ee3fb4a`

## P3-047 · `concept:c_1ea06745ce10da94`

- Metadata label: `상속인 금융거래조회`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_hrpe_hist` — 상속인 금융거래조회
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystHrpeHistInq/selectScrn.do
    - content_sha256: `50285fcc51505cc304aaec963e33d93981983b989497ca989d8eb9f22b027e61`

## P3-048 · `concept:c_da7426f8cd4b7af9`

- Metadata label: `상황선택`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `mtrs_stut_chc` — 상황선택
    - URL: https://fins.kdic.or.kr/ir/aplygudn/MtrsStutChc/selectScrn.do
    - content_sha256: `2b85e52da3cf42af3b46e2856b203a7a84395366dd7ec29bc6137536491bbedb`

## P3-049 · `concept:c_35ac7643177bb2aa`

- Metadata label: `소명 및 이의제기`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_objc` — 부보금융회사조사 소명 및 이의제기 신청
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaExplPrtsAplyGudn/selectScrn.do
    - content_sha256: `55199305c163c5f4fbd7c9e307ab0f28c897828356d40640b938501adbbb0187`

## P3-050 · `concept:c_0335dc25a8783d69`

- Metadata label: `소명및이의제기신청`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_objc` — 부보금융회사조사 소명 및 이의제기 신청
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaExplPrtsAplyGudn/selectScrn.do
    - content_sha256: `55199305c163c5f4fbd7c9e307ab0f28c897828356d40640b938501adbbb0187`

## P3-051 · `concept:c_008151b80c2c9d5d`

- Metadata label: `수취인_유의사항`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `receiver_attention` — 착오송금수취인 유의사항
    - URL: https://fins.kdic.or.kr/ir/addrse/AddrseAttnMttr/selectScrn.do
    - content_sha256: `eef6c873be4dc583038bf1a4e3e394150b2933918a89740e8f92c9580cc7a4e4`

## P3-052 · `concept:c_b2cfc8f3a944e190`

- Metadata label: `신고센터`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_center` — 신고센터
    - URL: https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do
    - content_sha256: `dba66fb0b1581bf925c8cc2eff706e7efe2468c6ad22d9b6fd438d70e51cd799`

## P3-053 · `concept:c_0b38f8efe27f5bc7`

- Metadata label: `신고센터 소개`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_ilgl_intro` — 신고센터 소개
    - URL: https://www.kdic.or.kr/sp/sprtfund/SprtFndIvsfalUnrlIlglDclrGudn/selectScrn.do
    - content_sha256: `06f9fa77314a9075fadc91c9f878487b8579376bf58edbf0f09f7fcfb95cad70`

## P3-054 · `concept:c_1bdf6485a85e2b7a`

- Metadata label: `신용회복 지원`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_credit_sprt` — 신용회복 지원
    - URL: https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtCredRcvrySprt/selectScrn.do
    - content_sha256: `f431a549eade658ea9f1723718b7d86ba1cc5001d9be77af65c1c35c3550ed01`

## P3-055 · `concept:c_2d53b0db833d2898`

- Metadata label: `신청대상여부 확인`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_qlfc_check` — 신청대상여부 확인 (자가진단)
    - URL: https://fins.kdic.or.kr/ir/msdrpr/selectAplyQlfcIdntyRslt.do
    - content_sha256: `c6364958af05b92718e2fdc11be7a6d69921aaf04eed20a3f7bb869499b11e05`

## P3-056 · `concept:c_f9833a8d9f0af6bf`

- Metadata label: `신청대상여부 확인 (자가진단)`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_qlfc_check` — 신청대상여부 확인 (자가진단)
    - URL: https://fins.kdic.or.kr/ir/msdrpr/selectAplyQlfcIdntyRslt.do
    - content_sha256: `c6364958af05b92718e2fdc11be7a6d69921aaf04eed20a3f7bb869499b11e05`

## P3-057 · `concept:c_9d49654cd2f061a4`

- Metadata label: `신청방법`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_apply_mthd` — 착오송금반환지원 신청방법
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyMthd/selectScrn.do
    - content_sha256: `c8d0393d679d1cf9163cce167b75b6353e4d8297e7cc38e807a08dec4a06889a`

## P3-058 · `concept:c_4ca7f75d2ec3bd7b`

- Metadata label: `신청시 구비서류`
- Evidence usage: 1 document(s); service(s): `예금보험금 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ms_poss_dcmnt` — 신청시 구비서류
    - URL: https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyPossDcmnt/selectScrn.do
    - content_sha256: `7f921cea8add94b1aa2e3b473a595420f648000c9dd90cedb73bd38d720f59fb`

## P3-059 · `concept:c_addfc0185edb571b`

- Metadata label: `신탁부동산관리체계`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_trst_mng` — 신탁부동산관리체계
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestMngStm.do
    - content_sha256: `131d34d20ced7ed553141591e715e3c65fe5572f11a75fe70afff7abf17aa6d3`

## P3-060 · `concept:c_6c704a1d32d87ba2`

- Metadata label: `신탁부동산현황`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_trst_psta` — 신탁부동산현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestPsta.do
    - content_sha256: `bf33dc193dfe488d6685a904bd1bc8b49c8f99be3822a77fddbcfcfb28ee6a8a`

## P3-061 · `concept:c_eb81d7d96ba4e901`

- Metadata label: `안내`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_itgr_aply` — 안내
    - URL: https://fins.kdic.or.kr/ua/aplygudn/NramtItgrAplyItrdMthdGudn/selectScrn.do
    - content_sha256: `c7fee2ab2ce3bd2ec489f51236ea07f0cb6d931496e75cbed1299466ba4f1898`

## P3-062 · `concept:c_a26428762ffd7da4`

- Metadata label: `안내자료 다운로드`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_gudn_data` — 안내자료 다운로드
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystDataDwnldList.do
    - content_sha256: `277bc8673d7e26f7c773524f321fdd3ceea6903ab7019980e37b7c3dcd36244d`

## P3-063 · `concept:c_a8f077467f3347be`

- Metadata label: `예금보험금 신청 절차`
- Evidence usage: 1 document(s); service(s): `예금보험금 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ms_aply_proc` — 예금보험금 신청절차
    - URL: https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do
    - content_sha256: `b398772e990453abd83695a258c409ec8a9dc4e6dbd19844a64aba34a498bba0`

## P3-064 · `concept:c_bdf7bad37a1447c3`

- Metadata label: `예금보험금 신청절차`
- Evidence usage: 1 document(s); service(s): `예금보험금 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ms_aply_proc` — 예금보험금 신청절차
    - URL: https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do
    - content_sha256: `b398772e990453abd83695a258c409ec8a9dc4e6dbd19844a64aba34a498bba0`

## P3-065 · `concept:c_7caf02c67727c3b6`

- Metadata label: `예금보험금이란?`
- Evidence usage: 1 document(s); service(s): `예금보험금 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ms_expln` — 예금보험금이란?
    - URL: https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do
    - content_sha256: `8a9ad3e4e641bff847e916ef4810d48562abc5fe0834288b074968f295c758a6`

## P3-066 · `concept:c_88b83dc8f903c686`

- Metadata label: `예금보호 로고 사용 안내`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_logo` — 예금보호 로고 사용 안내
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLogoUseGudn/selectScrn.do
    - content_sha256: `b13558ea8d7751e0ce05b5495297e8e0052178c445171ce682a47c3552951609`

## P3-067 · `concept:c_35005b837bcd53ab`

- Metadata label: `예금자 대상 전화문의 안내`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_tel_qust` — 예금자 대상 전화문의 안내
    - URL: https://fins.kdic.or.kr/ua/aplygudn/DpstrTrgtTelQustGudn/selectScrn.do
    - content_sha256: `39d6f5311215c364f8533142690c38f74f315b04338d057b1a401abeb43e900f`

## P3-068 · `concept:c_035f09e117783272`

- Metadata label: `예금자보호제도`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_syst` — 예금자보호제도
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSyst/selectScrn.do
    - content_sha256: `349ad69487c4cffaaf259bb5e09ec272dddefd39fbe410c307982b48c70f4150`

## P3-069 · `concept:c_340a7686f10d88bd`

- Metadata label: `예금자보호제도 FAQ`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_faq_page` — 예금자보호제도 FAQ
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystFaq/selectScrn.do
    - content_sha256: `053957508cb2b05942fa36d7ef48414f9c69b9da76654e53d6f3163a8a80d186`

## P3-070 · `concept:c_9627bdfe5acfa166`

- Metadata label: `예금자보호한도(해외)`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_ovrs` — 예금자보호한도(해외)
    - URL: https://www.kdic.or.kr/di/bzpblnt/selectPbcrPblntProtLmtsOvrs.do
    - content_sha256: `1a4a8bbbe9da470007dbc09feca00130e109708b3b8c0a4dda02f3f65e1d9459`

## P3-071 · `concept:c_ca4e186d69fc3c0b`

- Metadata label: `유의사항`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_attention` — 착오송금인 유의사항
    - URL: https://fins.kdic.or.kr/ir/msdrpr/MsdrprAttnMttr/selectScrn.do
    - content_sha256: `963ad6c3ea313510e69065cb12dfc64f66102c94bf0c45cea0f27ac18f3f60c7`

## P3-072 · `concept:c_fb68b1ac497f5069`

- Metadata label: `은닉재산신고 FAQ`
- Evidence usage: 1 document(s); service(s): `은닉재산 신고`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `ha_faq_dclr` — 은닉재산신고 FAQ
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqCncmPrptDclr.do
    - content_sha256: `9e72acbd7c27d0e6d80d0fc0c2e41a7b0a4d295c4d3d9790ef5eb6b9aaad5039`

## P3-073 · `concept:c_ec9c3ff287ee767b`

- Metadata label: `저축은행변경이력`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_svbk_hist` — 저축은행변경이력
    - URL: https://www.kdic.or.kr/sp/dpstrprot/selectProtSystSvbkChgHstry.do
    - content_sha256: `f7883d0f99f2f432c3ffd4c4e93895df9ae78050f71b6a646f6b3a8d0afabf5c`

## P3-074 · `concept:c_132955c7d26f2ff6`

- Metadata label: `절차`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_proc` — 착오송금반환지원 절차
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrdProc/selectScrn.do
    - content_sha256: `0a8b549ed1fb9cde87c259751d0a5916db2b5edfc1811b7ad7413bb30deabce7`

## P3-075 · `concept:c_5b4540e54140f019`

- Metadata label: `제도란`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_itrd` — 착오송금반환지원 제도란
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrd/selectScrn.do
    - content_sha256: `78b2c5fd989beb7c83e6e5564bacf232e3ab05fe011f609ff3cb76fe6591d212`

## P3-076 · `concept:c_19ff75362e1f3c6b`

- Metadata label: `조사업무 소개`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_josa_itrd` — 부보금융회사조사 업무 소개
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaItrd/selectScrn.do
    - content_sha256: `9edde39f7b3f5537ecdae0df628602c25ea1691f536c82fc3a8b2d8ee0fd868a`

## P3-077 · `concept:c_637a0e93c8785287`

- Metadata label: `착오송금 반환지원제도`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_aply_trgt` — 착오송금반환지원 신청대상
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyTrgt/selectScrn.do
    - content_sha256: `59dc690d463cc8be1cc8bb64b0d94ffddd53dbe50698493be796c8c21e05f740`

## P3-078 · `concept:c_4d1e7b824eca0319`

- Metadata label: `착오송금반환지원 신청대상`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_aply_trgt` — 착오송금반환지원 신청대상
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyTrgt/selectScrn.do
    - content_sha256: `59dc690d463cc8be1cc8bb64b0d94ffddd53dbe50698493be796c8c21e05f740`

## P3-079 · `concept:c_a8f7d97fb324c42d`

- Metadata label: `착오송금반환지원 신청방법`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_apply_mthd` — 착오송금반환지원 신청방법
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyMthd/selectScrn.do
    - content_sha256: `c8d0393d679d1cf9163cce167b75b6353e4d8297e7cc38e807a08dec4a06889a`

## P3-080 · `concept:c_ef419af38d852f47`

- Metadata label: `착오송금반환지원 절차`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_proc` — 착오송금반환지원 절차
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrdProc/selectScrn.do
    - content_sha256: `0a8b549ed1fb9cde87c259751d0a5916db2b5edfc1811b7ad7413bb30deabce7`

## P3-081 · `concept:c_fd6bb44fcceba87e`

- Metadata label: `착오송금반환지원 제도란`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `kmrs_itrd` — 착오송금반환지원 제도란
    - URL: https://www.kdic.or.kr/sp/kmrs/kmrsItrd/selectScrn.do
    - content_sha256: `78b2c5fd989beb7c83e6e5564bacf232e3ab05fe011f609ff3cb76fe6591d212`

## P3-082 · `concept:c_ea5acfa92394ba44`

- Metadata label: `착오송금수취인 유의사항`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `receiver_attention` — 착오송금수취인 유의사항
    - URL: https://fins.kdic.or.kr/ir/addrse/AddrseAttnMttr/selectScrn.do
    - content_sha256: `eef6c873be4dc583038bf1a4e3e394150b2933918a89740e8f92c9580cc7a4e4`

## P3-083 · `concept:c_9b6712000f4d1300`

- Metadata label: `착오송금인 유의사항`
- Evidence usage: 1 document(s); service(s): `착오송금 반환 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `sender_attention` — 착오송금인 유의사항
    - URL: https://fins.kdic.or.kr/ir/msdrpr/MsdrprAttnMttr/selectScrn.do
    - content_sha256: `963ad6c3ea313510e69065cb12dfc64f66102c94bf0c45cea0f27ac18f3f60c7`

## P3-084 · `concept:c_c4f8b4a53b142a0a`

- Metadata label: `채무정보 조회 및 상담신청`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_info_aply` — 채무정보 조회 ＆ 상담신청
    - URL: https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do
    - content_sha256: `7a5d97ec59ed45204a22616c03f2525a1a45837f427ee43a68ebc5b16f6b7e14`

## P3-085 · `concept:c_74952948bd1147a6`

- Metadata label: `채무정보 조회 ＆ 상담신청`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_info_aply` — 채무정보 조회 ＆ 상담신청
    - URL: https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do
    - content_sha256: `7a5d97ec59ed45204a22616c03f2525a1a45837f427ee43a68ebc5b16f6b7e14`

## P3-086 · `concept:c_8e9f45db00366d53`

- Metadata label: `채무정보조회 FAQ`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_faq_inq` — 채무정보조회 FAQ
    - URL: https://fins.kdic.or.kr/cm/bbs/selectFaqLbltInfoInq.do
    - content_sha256: `1c899cabed5073edfacd1f0b66768b9fc9f30442f4f073126e75f4d6411f4146`

## P3-087 · `concept:c_4fba11fc0d99225c`

- Metadata label: `채무조정`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_kruc` — 채무조정
    - URL: https://www.kdic.or.kr/di/relsite/PbcrKrncLblarb/selectScrn.do
    - content_sha256: `12dfb1ce59d6d3fab50a7e8e4628cdf253f6ab7d36844933fe69302c430d6143`

## P3-088 · `concept:c_8306dbfed40e512f`

- Metadata label: `채무조정제도`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_system` — 채무조정제도
    - URL: https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltAjmtSyst/selectScrn.do
    - content_sha256: `fab47dae07d654ef663346619ff27c9c5758ad6cfa97b2a6489be1ffbb9b1387`

## P3-089 · `concept:c_bcafbdc1d9dfd547`

- Metadata label: `특별자산관리체계`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_spcl_mng` — 특별자산관리체계
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstMngStm.do
    - content_sha256: `3a0860d1b3bf0214ea9a36dfec58a05c1005a3aa083c8caf0d0bebb3a204d753`

## P3-090 · `concept:c_b6a885b4154a1e9e`

- Metadata label: `특별자산현황`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_spcl_ast` — 특별자산현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstPsta.do
    - content_sha256: `3f959b62d5de6190d49af788f352f16f0b8ae76684dbf59d2fe266e8b7416dbc`

## P3-091 · `concept:c_a27f421d12b3564b`

- Metadata label: `파산면책`
- Evidence usage: 1 document(s); service(s): `채무조정 안내`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dr_psn_br` — 파산면책
    - URL: https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnBr/selectScrn.do
    - content_sha256: `378fad2a221975f3ea53db06c46242f0cc3c871334bb3b5ec66a173292ec3e32`

## P3-092 · `concept:c_572776d78d64263b`

- Metadata label: `파산재단관리`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_mng` — 파산재단관리
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtMng.do
    - content_sha256: `ffb3d70566ced75adac265f8a23d0f9c9ea47178ba2c4bd3e413e8bd86eb5188`

## P3-093 · `concept:c_1bdf92f70ac093d9`

- Metadata label: `파산재단현황`
- Evidence usage: 1 document(s); service(s): `고객 미수령금 신청`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `uc_bkrp_fndt` — 파산재단현황
    - URL: https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtPsta.do
    - content_sha256: `4ac0da576f6f00b5f460568f03a99ed4ce6a421060f33dca66adfaddd1d15946`

## P3-094 · `concept:c_527a3c9463713818`

- Metadata label: `표시·설명·확인 제도 관련 FAQ`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_gudn_faq` — 표시·설명·확인 제도 관련 FAQ
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtSystFaq/selectScrn.do
    - content_sha256: `c05522f4f7b5b14e720c8059445f3fc6e75b62698f71fdb50aa028837d3b07c1`

## P3-095 · `concept:c_fef052cdef70a2cd`

- Metadata label: `표시·설명·확인 제도 안내`
- Evidence usage: 1 document(s); service(s): `예금자보호제도`
- Review status: `proposed`
- Decision: `pending` (`approved` | `rejected` | `needs_split`)
- Canonical label: 
- Concept kind: 
- Synonyms (with page evidence): 
- Review note: 
- Evidence:
  - `dp_gudn` — 표시·설명·확인 제도 안내
    - URL: https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtGudn/selectScrn.do
    - content_sha256: `dccd0b0bcc9c2becc411d6e87f3e70e1606885ba6d567986bf81e32ccb242e23`

