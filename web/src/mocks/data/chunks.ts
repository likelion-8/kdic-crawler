/** 청크 목 데이터 — 실제 data/chunks_all.jsonl(494청크)에서 28건.
 *
 * chunk_id 규칙은 CM-DF-002 01절: 단일 청크 페이지는 `#0`을 붙이지 않는다(= page_id와 같다).
 * title은 코퍼스에 없는 파생값 — 청크 본문 첫 문장을 잘라 만든 목록 표시용이다. */

export interface KbChunk {
  chunk_id: string
  page_id: string
  /** 페이지 안 순번. 단일 청크는 0 */
  seq: number
  /** 목록 표시용 파생 제목 */
  title: string
  /** 본문 글자 수 — 상세 패널 "#0 · 신청 대상 (412자)" 표기용 */
  chars: number
  preview: string
}

export const MOCK_CHUNKS: KbChunk[] = [
  { chunk_id: "faq_msdr_apply#0", page_id: "faq_msdr_apply", seq: 0, title: "질문 착오송금 반환지원 대상 금액은 얼마까지인가요", chars: 124, preview: "질문 착오송금 반환지원 대상 금액은 얼마까지인가요? 열기 답변 공사의 착오송금 반환지원 대상 금액은 착오송금 건당 5만원 이상…" },
  { chunk_id: "faq_msdr_apply#1", page_id: "faq_msdr_apply", seq: 1, title: "질문 그 외에도 착오송금 반환지원 대상이 아닌 경우…", chars: 206, preview: "질문 그 외에도 착오송금 반환지원 대상이 아닌 경우에는 어떤 것이 해당되나요? 열기 답변 ① 부당이득반환채권과 관련된 소송 또…" },
  { chunk_id: "faq_msdr_apply#2", page_id: "faq_msdr_apply", seq: 2, title: "질문 공동인증서가 보이지 않을 경우 어떻게 해야 하…", chars: 248, preview: "질문 공동인증서가 보이지 않을 경우 어떻게 해야 하나요? 열기 답변 금융결제원(yeskey.or.kr)의 MY인증(발급 및 관…" },
  { chunk_id: "faq_msdr_apply#3", page_id: "faq_msdr_apply", seq: 3, title: "질문 매입계약 체결 이후 계약이 해제되는 경우도 있…", chars: 217, preview: "질문 매입계약 체결 이후 계약이 해제되는 경우도 있나요? 열기 답변 매입계약 체결 이후 ① 거짓이나 부정한 방법으로 지원 신청…" },
  { chunk_id: "faq_msdr_apply#4", page_id: "faq_msdr_apply", seq: 4, title: "질문 온라인으로만 착오송금 반환지원 신청이 가능한가…", chars: 106, preview: "질문 온라인으로만 착오송금 반환지원 신청이 가능한가요? 열기 답변 아닙니다. 착오송금 반환지원 신청은 홈페이지를 통한 온라인 …" },
  { chunk_id: "faq_msdr_apply#5", page_id: "faq_msdr_apply", seq: 5, title: "질문 착오송금 반환지원 신청 접수부터 실제 반환까지…", chars: 124, preview: "질문 착오송금 반환지원 신청 접수부터 실제 반환까지 예상되는 소요 기간은 어떻게 되나요? 열기 답변 자진반환 및 지급명령을 통…" },
  { chunk_id: "faq_msdr_apply#6", page_id: "faq_msdr_apply", seq: 6, title: "질문 보이스피싱 피해도 착오송금 반환지원 신청이 가…", chars: 188, preview: "질문 보이스피싱 피해도 착오송금 반환지원 신청이 가능한가요? 열기 답변 보이스피싱의 경우「전기통신금융사기 피해 방지 및 피해금…" },
  { chunk_id: "faq_msdr_apply#7", page_id: "faq_msdr_apply", seq: 7, title: "질문 Toss나 카카오페이와 같이 간편송금을 통해 …", chars: 327, preview: "질문 Toss나 카카오페이와 같이 간편송금을 통해 발생한 착오송금도 지원대상이 되나요? 열기 답변 Toss 등 선불전자지급수단…" },
  { chunk_id: "faq_msdr_apply#8", page_id: "faq_msdr_apply", seq: 8, title: "질문 외국은행 또는 국내은행의 해외지점으로 보낸 착…", chars: 127, preview: "질문 외국은행 또는 국내은행의 해외지점으로 보낸 착오송금도 반환지원 신청할 수 있나요? 열기 답변 착오송금 수취인 계좌가 외국…" },
  { chunk_id: "faq_msdr_apply#9", page_id: "faq_msdr_apply", seq: 9, title: "질문 반환지원 적용 대상이 되는 송금·수취기관은 어…", chars: 318, preview: "질문 반환지원 적용 대상이 되는 송금·수취기관은 어디인가요? 열기 답변 은행(외은지점, 농협은행, 수협은행, 산업은행, 중소기…" },
  { chunk_id: "faq_msdr_apply#10", page_id: "faq_msdr_apply", seq: 10, title: "질문6 참조) 1 2 다음 페이지 마지막 페이지 퀵…", chars: 317, preview: "질문6 참조) 1 2 다음 페이지 마지막 페이지 퀵메뉴 금융회사를 통한 반환절차를 거치지 않고 착오송금 즉시 예보에 반환지원 …" },
  { chunk_id: "sender_docs#0", page_id: "sender_docs", seq: 0, title: "착오송금인 착오송금수취인 착오송금 신청 구분 | 온…", chars: 476, preview: "착오송금인 착오송금수취인 착오송금 신청 구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 본인 | 공통 서…" },
  { chunk_id: "sender_docs#1", page_id: "sender_docs", seq: 1, title: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 …", chars: 664, preview: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 대리인 | 공통 서류 | | 대리인 확인용 신분증 (주민…" },
  { chunk_id: "sender_docs#2", page_id: "sender_docs", seq: 2, title: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 …", chars: 325, preview: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 착오송금인의 인감 날인된 채권양도 통지 위임장 스캔파일 …" },
  { chunk_id: "sender_docs#3", page_id: "sender_docs", seq: 3, title: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 …", chars: 560, preview: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 비법인단체를 대리하는 경우 고유번호증 파일업로드 | 비법…" },
  { chunk_id: "sender_docs#4", page_id: "sender_docs", seq: 4, title: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 …", chars: 356, preview: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 해외거주자를 대리하는 경우 인감증명서제출이 불가능한경우 …" },
  { chunk_id: "sender_docs#5", page_id: "sender_docs", seq: 5, title: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 …", chars: 278, preview: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발…" },
  { chunk_id: "sender_docs#6", page_id: "sender_docs", seq: 6, title: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 …", chars: 496, preview: "구분 | 온라인 신청 | 방문 신청 | 관련 서식 | 발급처 및 비고 반환금 수령계좌 변경 | 통장사본 파일 업로드 | 수령계…" },
  { chunk_id: "dp_protlmts", page_id: "dp_protlmts", seq: 0, title: "예금자보호제도는 다수의 소액예금자를 우선 보호하고 …", chars: 1166, preview: "예금자보호제도는 다수의 소액예금자를 우선 보호하고 부실 금융회사를 선택한 예금자도 일정부분 책임을 분담한다는 차원에서 예금의 …" },
  { chunk_id: "kmrs_apply_mthd", page_id: "kmrs_apply_mthd", seq: 0, title: "신청방법 온라인 신청 사이트 : fins.kdic.…", chars: 250, preview: "신청방법 온라인 신청 사이트 : fins.kdic.or.kr (상단 아이콘 클릭 시 사이트 연결) 접속방법 : PC (모바일은…" },
  { chunk_id: "dp_faq_page#0", page_id: "dp_faq_page", seq: 0, title: "질문 예금보호한도 1억원은 언제부터 적용되었나요", chars: 119, preview: "질문 예금보호한도 1억원은 언제부터 적용되었나요? 열기 답변 2025년 9월 1일부터 예금보호한도 1억원이 적용되고 있습니다.…" },
  { chunk_id: "dp_faq_page#1", page_id: "dp_faq_page", seq: 1, title: "질문 1억원을 보호 받기 위해 별도로 신청을 해야 …", chars: 226, preview: "질문 1억원을 보호 받기 위해 별도로 신청을 해야 하나요? 열기 답변 상향된 예금보호한도 적용을 위해 별도의 신청 절차는 필요…" },
  { chunk_id: "dp_faq_page#2", page_id: "dp_faq_page", seq: 2, title: "질문 어떤 금융회사의 예금이 보호되나요", chars: 284, preview: "질문 어떤 금융회사의 예금이 보호되나요? 열기 답변 ☞ 예금보험공사 홈페이지 > 제도·정책 > 예금자보호제도 > 보호대상 > …" },
  { chunk_id: "dp_faq_page#3", page_id: "dp_faq_page", seq: 3, title: "질문 어떤 금융상품이 보호되나요", chars: 348, preview: "질문 어떤 금융상품이 보호되나요? 열기 답변 ☞ 예금보험공사 홈페이지 > 제도·정책 > 예금자보호제도 > 보호대상 > 금융상품…" },
  { chunk_id: "ha_faq_dclr#0", page_id: "ha_faq_dclr", seq: 0, title: "질문 기타 자세한 사항을 알고싶으면 어떻게 하면 되…", chars: 145, preview: "질문 기타 자세한 사항을 알고싶으면 어떻게 하면 되나요? 열기 답변 기타 자세한 사항은 예금보험공사 홈페이지(www.kdic.…" },
  { chunk_id: "ha_faq_dclr#1", page_id: "ha_faq_dclr", seq: 1, title: "질문 은닉재산신고 포상제도는 어떻게 되나요", chars: 724, preview: "질문 은닉재산신고 포상제도는 어떻게 되나요? 열기 답변 □ 포상금 지급 기준 회수기여금액 | 포상금 5억원 이하 | 회수기여금…" },
  { chunk_id: "ha_faq_dclr#2", page_id: "ha_faq_dclr", seq: 2, title: "질문 신고대상자가 부실관련자인지 여부를 어떻게 알수…", chars: 143, preview: "질문 신고대상자가 부실관련자인지 여부를 어떻게 알수있나요? 열기 답변 신고대상자(법인 포함)가 부실관련자인지 여부는 신고센터와…" },
  { chunk_id: "ha_faq_dclr#3", page_id: "ha_faq_dclr", seq: 3, title: "질문 익명이나 가명으로 신고하는 것도 가능한가요", chars: 179, preview: "질문 익명이나 가명으로 신고하는 것도 가능한가요? 열기 답변 은닉재산의 신고시 허위 또는 무고성 신고 등의 남발을 방지하기 위…" },
]
