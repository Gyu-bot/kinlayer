import type { RelationshipProfileRegistry } from "./data";

// Synthetic metadata used only by UI tests; production options come from the API.
export const relationshipProfileFixture: RelationshipProfileRegistry = {
  version: "relationship-profile-v1",
  axes: {
    closeness: { label: "친밀도", description: "내가 느끼는 친밀도", values: [
      { value: "recognize", label: "얼굴만 아는", description: "알아볼 수 있는 사람" },
      { value: "acquainted", label: "알고 지내는", description: "알고 지내는 사이" },
      { value: "comfortable", label: "편한", description: "편하게 대화할 수 있는 사이" },
      { value: "close", label: "친한", description: "친하다고 느끼는 사이" },
      { value: "very_close", label: "매우 친한", description: "매우 친하다고 느끼는 사이" },
    ] },
    importance: { label: "중요도", description: "나에게 중요한 정도", values: [
      { value: "normal", label: "보통", description: "보통" },
      { value: "important", label: "중요", description: "중요" },
      { value: "very_important", label: "매우 중요", description: "매우 중요" },
    ] },
    interaction_frequency: { label: "교류 빈도", description: "내가 직접 표현한 교류 빈도", values: [
      { value: "frequent", label: "자주", description: "자주 교류" },
      { value: "occasional", label: "가끔", description: "가끔 교류" },
      { value: "rare", label: "드물게", description: "드물게 교류" },
      { value: "none", label: "없음", description: "교류 없음" },
    ] },
    connection_state: { label: "관계 상태", description: "현재 연결 상태", values: [
      { value: "maintained", label: "유지", description: "유지 중" },
      { value: "distant", label: "뜸해짐", description: "뜸해짐" },
      { value: "disconnected", label: "단절", description: "단절" },
    ] },
  },
};
