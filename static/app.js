const root = document.documentElement;
const themeButton = document.getElementById("theme-toggle");
const preferredTheme = window.matchMedia("(prefers-color-scheme: dark)");

function setTheme(theme) {
  root.dataset.theme = theme;
  const isDark = theme === "dark";
  document.querySelector('meta[name="theme-color"]').content = isDark ? "#10131d" : "#f5f7ff";
  if (themeButton) {
    themeButton.querySelector(".theme-icon").textContent = isDark ? "☀" : "☾";
    themeButton.querySelector(".theme-label").textContent = isDark ? "Light mode" : "Dark mode";
    themeButton.setAttribute("aria-label", `Switch to ${isDark ? "light" : "dark"} mode`);
  }
}

setTheme(localStorage.getItem("internloom-theme") || (preferredTheme.matches ? "dark" : "light"));

if (themeButton) {
  themeButton.addEventListener("click", () => {
    const theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("internloom-theme", theme);
    setTheme(theme);
  });
}

document.querySelectorAll("[data-upload-input]").forEach((input) => {
  input.addEventListener("change", () => {
    const status = document.querySelector(`[data-upload-status="${input.id}"]`);
    if (!status) return;
    status.textContent = input.files.length ? `${input.files.length} document${input.files.length === 1 ? "" : "s"} selected` : "PDF, DOCX, or DOC";
    input.closest(".upload-card").classList.toggle("has-files", Boolean(input.files.length));
  });
});

const form = document.getElementById("shortlist-form");
if (form) {
  form.addEventListener("submit", () => {
    const button = form.querySelector(".primary-action");
    button.classList.add("is-loading");
    button.querySelector(".button-text").textContent = "Reviewing resumes";
  });
}

const table = document.getElementById("shortlist-table");
const search = document.getElementById("candidate-search");

if (search && table) {
  search.addEventListener("input", () => {
    const query = search.value.toLowerCase();
    [...table.tBodies[0].rows].forEach((row) => {
      row.hidden = !row.innerText.toLowerCase().includes(query);
    });
  });

  table.querySelectorAll("th[data-key]").forEach((header) => {
    header.addEventListener("click", () => {
      const column = [...header.parentNode.children].indexOf(header);
      const numeric = header.dataset.key === "score";
      const rows = [...table.tBodies[0].rows];
      const direction = header.dataset.direction === "asc" ? -1 : 1;
      rows.sort((first, second) => {
        const firstValue = first.cells[column].dataset.sort || first.cells[column].innerText;
        const secondValue = second.cells[column].dataset.sort || second.cells[column].innerText;
        return (numeric ? Number(firstValue) - Number(secondValue) : firstValue.localeCompare(secondValue)) * direction;
      });
      rows.forEach((row) => table.tBodies[0].appendChild(row));
      table.querySelectorAll("th[data-key]").forEach((item) => delete item.dataset.direction);
      header.dataset.direction = direction === 1 ? "asc" : "desc";
    });
  });
}

const exportButton = document.getElementById("export-csv");
if (exportButton) {
  exportButton.addEventListener("click", () => {
    const candidates = JSON.parse(document.getElementById("candidate-data").textContent);
    const rows = [["Candidate", "File", "Score", "Confidence", "Parse Quality", "Reasoning"]];
    candidates.forEach((candidate) => rows.push([candidate.name, candidate.file, candidate.score, candidate.confidence, candidate.parse_quality, candidate.reasoning.join(" | ")]));
    const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.download = "internloom_shortlist.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  });
}
