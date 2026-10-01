import { useEffect, useState, type MouseEvent } from "react";
import { Shell } from "./v2/Shell";
import { People } from "./v2/People";
import { Person } from "./v2/Person";
import { Graph } from "./v2/Graph";
import { Changes, Memories, SourcePage } from "./v2/Memories";
import { Diagnostics, Search, Settings } from "./v2/Support";

export default function App() {
  const [location, setLocation] = useState(
    window.location.pathname + window.location.search,
  );
  useEffect(() => {
    const changed = () =>
      setLocation(window.location.pathname + window.location.search);
    window.addEventListener("popstate", changed);
    return () => window.removeEventListener("popstate", changed);
  }, []);
  function navigate(path: string) {
    if (path === location) return;
    window.history.pushState({}, "", path);
    setLocation(path);
    window.scrollTo?.(0, 0);
  }
  function follow(event: MouseEvent) {
    const link = (event.target as HTMLElement).closest("a");
    if (
      !link ||
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      link.target ||
      link.hasAttribute("download")
    )
      return;
    const url = new URL(link.href);
    if (url.origin !== window.location.origin || url.hash) return;
    event.preventDefault();
    navigate(url.pathname + url.search);
  }
  const path = location.split("?")[0];
  const person = path.match(/^\/people\/([^/]+)$/),
    source = path.match(/^\/sources\/([^/]+)$/);
  let content;
  if (path === "/" || path === "/people" || path === "/people/new")
    content = <People onNavigate={navigate} />;
  else if (person) content = <Person id={person[1]} onNavigate={navigate} />;
  else if (path === "/graph") content = <Graph onNavigate={navigate} />;
  else if (path === "/memories") content = <Memories onNavigate={navigate} />;
  else if (path === "/changes" || path === "/reviews") content = <Changes />;
  else if (source) content = <SourcePage id={source[1]} />;
  else if (path === "/settings") content = <Settings onNavigate={navigate} />;
  else if (path === "/search" || path === "/retrieval-debug")
    content = <Search onNavigate={navigate} />;
  else if (["/legacy", "/candidates", "/agent-operations"].includes(path))
    content = <Diagnostics onNavigate={navigate} />;
  else
    content = (
      <div className="panel empty-state">
        <h1>페이지를 찾을 수 없어요</h1>
        <a className="button primary" href="/people">
          사람 목록으로
        </a>
      </div>
    );
  return (
    <div onClick={follow}>
      <Shell path={path === "/" ? "/people" : path} onNavigate={navigate}>
        <div key={location} className="route-content">
          {content}
        </div>
      </Shell>
    </div>
  );
}
