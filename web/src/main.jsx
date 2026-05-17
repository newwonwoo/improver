import React from "react";
import ReactDOM from "react-dom/client";
import Report from "./Report.jsx";
import sample from "./sample_result.json";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Report result={sample} />
  </React.StrictMode>,
);
