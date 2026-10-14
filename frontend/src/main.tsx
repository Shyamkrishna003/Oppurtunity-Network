// Must stay first: see the file.
import "./app/strictPolicy";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/nunito";

import { App } from "./app/App";
import "./styles/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
