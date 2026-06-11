import {useEffect, useState} from "react";

import {apiUrl} from "./api/client";
import {Candidates} from "./routes/Candidates";
import {Graph} from "./routes/Graph";
import {NewPerson} from "./routes/NewPerson";
import {PeopleList} from "./routes/PeopleList";
import {PersonDetail} from "./routes/PersonDetail";
import {RetrievalDebug} from "./routes/RetrievalDebug";
import {Settings} from "./routes/Settings";

const routes = [
  {label: "People", path: "/people"},
  {label: "New person", path: "/people/new"},
  {label: "Candidates", path: "/candidates"},
  {label: "Graph", path: "/graph"},
  {label: "Retrieval debug", path: "/retrieval-debug"},
  {label: "Settings", path: "/settings"},
];

function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const handler = () => setPath(window.location.pathname);
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  function navigate(nextPath: string) {
    window.history.pushState({}, "", nextPath);
    setPath(nextPath);
  }

  const normalizedPath = path === "/" ? "/people" : path;
  const personMatch = normalizedPath.match(/^\/people\/([^/]+)$/);
  let content = <PeopleList onNavigate={navigate} />;
  if (normalizedPath === "/people/new") {
    content = <NewPerson onNavigate={navigate} />;
  } else if (personMatch) {
    content = <PersonDetail id={personMatch[1]} onNavigate={navigate} />;
  } else if (normalizedPath === "/candidates") {
    content = <Candidates />;
  } else if (normalizedPath === "/graph") {
    content = <Graph />;
  } else if (normalizedPath === "/retrieval-debug") {
    content = <RetrievalDebug />;
  } else if (normalizedPath === "/settings") {
    content = <Settings />;
  }

  return (
    <main className="shell">
      <nav className="topbar" aria-label="Primary">
        <div className="nav-group">
          <button type="button" className="brand" onClick={() => navigate("/people")}>
            Kinlayer
          </button>
          {routes.map((route) => (
            <button
              type="button"
              className={normalizedPath === route.path ? "nav-link active" : "nav-link"}
              key={route.path}
              onClick={() => navigate(route.path)}
            >
              {route.label}
            </button>
          ))}
        </div>
        <span className="api-url">{apiUrl}</span>
      </nav>
      {content}
    </main>
  );
}

export default App;
