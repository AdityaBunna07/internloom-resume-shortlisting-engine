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
    candidates.forEach((candidate) => rows.push([
      candidate.name, candidate.file, candidate.score, candidate.confidence,
      candidate.parse_quality, candidate.reasoning.join(" | "),
    ]));
    const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.download = "internloom_shortlist.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  });
}
