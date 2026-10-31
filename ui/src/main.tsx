import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { takeTokenFromHash } from "./api";
import "./styles.css";

const token = takeTokenFromHash(); // #token=... → sessionStorage, adresten silinir

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App initialToken={token} />
  </StrictMode>,
);
