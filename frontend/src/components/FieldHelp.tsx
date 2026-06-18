type Props = {
  label: string;
  help?: string;
};

export function FieldHelp({label, help}: Props) {
  return (
    <span className="field-label">
      <span>{label}</span>
      {help ? <span className="field-help" aria-hidden="true">{help}</span> : null}
    </span>
  );
}

export const helpCopy = {
  sensitivity: {
    label: "Sensitivity",
    help: "이 정보가 얼마나 조심스럽게 다뤄져야 하는지",
  },
  policy: {
    label: "AI use policy",
    help: "답변에 직접 말해도 되는지, 내부 참고만 해야 하는지",
  },
  claim: {
    label: "Claim",
    help: "확인된 사실인지, 추론인지, 반복된 패턴인지",
  },
  status: {
    label: "Status",
    help: "현재 사용 중인지, 숨김/삭제된 기록인지",
  },
};
