import { type MouseEvent, type ReactNode, useEffect, useState } from "react";
import { BrandMark, Icon } from "./Icons";

const navigation = [
  { path: "/people", label: "사람", icon: "people" },
  { path: "/memories", label: "기억", icon: "layers" },
  { path: "/graph", label: "관계 그래프", icon: "graph" },
  { path: "/changes", label: "변경 이력", icon: "clock" },
];
const secondary = [
  { path: "/search", label: "기억 검색", icon: "search" },
  { path: "/settings", label: "설정", icon: "info" },
  { path: "/legacy", label: "이전 기록", icon: "archive" },
];

export function Shell({
  path,
  onNavigate,
  children,
}: {
  path: string;
  onNavigate: (path: string) => void;
  children: ReactNode;
}) {
  const [menu, setMenu] = useState(false);
  const previewLabel = import.meta.env.VITE_KINLAYER_PREVIEW_LABEL?.trim();
  const pathname = path.split("?")[0];
  const current = [...navigation, ...secondary].find(
    (item) => pathname === item.path || pathname.startsWith(`${item.path}/`),
  );
  useEffect(() => {
    setMenu(false);
  }, [path]);
  function go(event: MouseEvent<HTMLAnchorElement>, destination: string) {
    if (
      event.button ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    onNavigate(destination);
  }
  function link(item: (typeof navigation)[number]) {
    const active = current?.path === item.path;
    return (
      <a
        key={item.path}
        href={item.path}
        className={`nav-item ${active ? "active" : ""}`}
        aria-current={active ? "page" : undefined}
        onClick={(event) => go(event, item.path)}
      >
        <Icon name={item.icon} />
        <span>{item.label}</span>
      </a>
    );
  }
  return (
    <>
      <a className="skip-link" href="#main">
        본문으로 건너뛰기
      </a>
      <aside className="sidebar">
        <a
          href="/people"
          className="brand"
          onClick={(event) => go(event, "/people")}
          aria-label="Kinlayer 사람 화면"
        >
          <BrandMark />
          Kinlayer
        </a>
        <div className="workspace-name">
          <Icon name="lock" />
          나의 관계 공간
        </div>
        <div className="nav-label">사람과 함께 쌓은 기억</div>
        <nav className="navigation" aria-label="주요 탐색">
          {navigation.map(link)}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Icon name="layers" />
            기억은 쌓이고,
            <br />
            맥락은 더 선명해져요.
          </div>
          <nav aria-label="보조 탐색">{secondary.map(link)}</nav>
        </div>
      </aside>
      <div className="app-frame">
        <header className="topbar">
          <div className="breadcrumbs">
            <a href="/people" onClick={(event) => go(event, "/people")}>
              <Icon name="home" />
              <span>내 관계 공간</span>
            </a>
            <Icon name="chevron" />
            <span className="current">
              {current?.label ||
                (pathname.startsWith("/sources/") ? "기억의 출처" : "Kinlayer")}
            </span>
          </div>
          <div className="topbar-controls">
            {previewLabel && (
              <span className="connection-label">{previewLabel}</span>
            )}
            <div className="shell-tools">
              <button
                type="button"
                className="icon-button"
                aria-label="검색과 설정 메뉴"
                aria-expanded={menu}
                aria-controls="shell-tools-menu"
                onClick={() => setMenu((value) => !value)}
              >
                <Icon name="list" />
              </button>
              {menu && (
                <nav
                  id="shell-tools-menu"
                  className="shell-tools-menu"
                  aria-label="검색과 설정"
                >
                  {secondary.map(link)}
                </nav>
              )}
            </div>
          </div>
        </header>
        <main className="main" id="main" tabIndex={-1}>
          {children}
          <footer className="page-footer">
            <span className="row">
              <Icon name="layers" />
              사람을 기억하고, 맥락을 연결하는 공간
            </span>
          </footer>
        </main>
      </div>
    </>
  );
}
