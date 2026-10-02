import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PersonDelete } from "./PersonDelete";
import type { Person } from "./data";

const fetchMock = vi.fn();
const person: Person = {
  id: "person-a", display_name: "김민지", canonical_name: "김민지", status: "active",
  system_role: null, is_system: false, properties: {}, created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z", last_referenced_at: null,
};
const deleted = { ...person, status: "deleted" };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true,
    value: function (this: HTMLDialogElement) { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true,
    value: function (this: HTMLDialogElement) { this.open = false; } });
});
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
  fetchMock.mockResolvedValue(response(deleted));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function show(target = person) {
  const onClose = vi.fn(), onDeleted = vi.fn();
  render(<PersonDelete person={target} onClose={onClose} onDeleted={onDeleted} />);
  return { onClose, onDeleted };
}
function confirm() { fireEvent.click(screen.getByRole("checkbox")); }
function submit() { fireEvent.click(screen.getByRole("button", { name: "인물 삭제" })); }
function requests(method: string) {
  return fetchMock.mock.calls.filter(([, init]) => (init?.method || "GET") === method);
}

describe("인물 삭제", () => {
  it("삭제 범위와 복구 한계를 안내하며 확인 없이 제출하거나 취소할 때는 요청하지 않는다", () => {
    const { onClose, onDeleted } = show();
    expect(screen.getByRole("heading", { name: "김민지" })).toBeInTheDocument();
    expect(screen.getByText("연결된 기억·프로필·관계·별칭과 원본 출처는 보존됩니다.")).toBeInTheDocument();
    expect(screen.getByText("보존된 기록은 기억 목록이나 관계 그래프에 계속 표시될 수 있습니다.")).toBeInTheDocument();
    expect(screen.getByText("현재는 삭제한 인물을 복구하는 기능이 없습니다.")).toBeInTheDocument();
    expect(screen.queryByLabelText("말한 사람")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("근거가 되는 발언·직접 입력")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "인물 삭제" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    confirm();
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("확인한 인물 하나만 삭제하며 연결 기록에 별도 삭제 요청을 보내지 않는다", async () => {
    const { onClose, onDeleted } = show();
    confirm();
    submit();
    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(new URL(fetchMock.mock.calls[0][0]).pathname).toBe("/api/entities/person-a");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
    expect(fetchMock.mock.calls[0][1]).not.toHaveProperty("body");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "삭제 완료" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("전송 중 연속 제출과 닫기·취소·Escape를 막아 삭제가 한 번만 실행된다", async () => {
    let resolveDelete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveDelete = resolve; });
    fetchMock.mockReturnValue(pending);
    const { onClose, onDeleted } = show();
    confirm();
    const dialog = screen.getByRole("dialog");
    act(() => {
      fireEvent.submit(dialog.querySelector("form")!);
      fireEvent.submit(dialog.querySelector("form")!);
    });
    expect(screen.getByRole("button", { name: "삭제 확인 중…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
    expect(onClose).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce();
    await act(async () => { resolveDelete(response(deleted)); await pending; });
    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce());
    expect(requests("DELETE")).toHaveLength(1);
  });

  it("삭제 응답이 끊어져도 같은 인물의 삭제 상태를 조회해 완료를 회복한다", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("응답 연결이 끊어졌어요.")).mockResolvedValueOnce(response(deleted));
    const { onDeleted } = show();
    confirm();
    submit();
    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce());
    expect(requests("DELETE")).toHaveLength(1);
    expect(requests("GET")).toHaveLength(1);
    expect(fetchMock.mock.calls.every(([url]) => new URL(url).pathname === "/api/entities/person-a")).toBe(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("실패 후 인물이 여전히 활성 상태이면 확인을 유지하고 명시적으로 재시도한다", async () => {
    fetchMock.mockResolvedValueOnce(response({ error: { code: "conflict", message: "다른 변경이 진행 중입니다." } }, 409))
      .mockResolvedValueOnce(response(person)).mockResolvedValueOnce(response(deleted));
    const { onDeleted } = show();
    confirm();
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("다른 변경이 진행 중입니다.");
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(requests("DELETE")).toHaveLength(1);
    submit();
    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce());
    expect(requests("DELETE")).toHaveLength(2);
    expect(requests("GET")).toHaveLength(1);
  });

  it("결과 조회도 실패하면 완료로 간주하지 않고 원래 오류와 확인 상태를 유지한다", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("삭제 응답이 끊어졌어요."))
      .mockRejectedValueOnce(new TypeError("조회 연결도 끊어졌어요."));
    const { onDeleted } = show();
    confirm();
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("삭제 응답이 끊어졌어요.");
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByRole("button", { name: "인물 삭제" })).toBeEnabled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["다른 인물", { ...deleted, id: "person-b" }],
    ["활성 상태", person],
    ["빈 응답", {}],
  ])("성공 응답이라도 %s이면 삭제 완료를 알리지 않는다", async (_label, invalid) => {
    fetchMock.mockResolvedValueOnce(response(invalid));
    const { onDeleted } = show();
    confirm();
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("선택한 인물의 삭제 완료를 확인하지 못했어요.");
    expect(onDeleted).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("불확실한 삭제 결과 조회가 다른 인물을 반환하면 완료로 처리하지 않는다", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("삭제 응답이 끊어졌어요."))
      .mockResolvedValueOnce(response({ ...deleted, id: "person-b" }));
    const { onDeleted } = show();
    confirm();
    submit();
    await screen.findByRole("alert");
    expect(onDeleted).not.toHaveBeenCalled();
    expect(requests("DELETE")).toHaveLength(1);
    expect(requests("GET")).toHaveLength(1);
  });

  it.each([
    ["본인", { system_role: "self" }],
    ["시스템 인물", { is_system: true }],
    ["다른 시스템 역할", { system_role: "assistant" }],
    ["삭제된 인물", { status: "deleted" }],
    ["병합된 인물", { status: "merged" }],
  ])("%s은 화면을 직접 열고 제출해도 삭제 요청을 보내지 않는다", (_label, properties) => {
    const { onDeleted } = show({ ...person, ...properties });
    expect(screen.getByRole("alert")).toHaveTextContent("현재 등록된 일반 인물만 삭제할 수 있어요.");
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "인물 삭제" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
