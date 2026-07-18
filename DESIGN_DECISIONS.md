# Design Decisions

## Multi-column PDFs

The parser obtains PyMuPDF text blocks with coordinates and groups their `x0` positions around the largest horizontal gap. It uses column ordering only when both groups have at least two blocks and the gap is a meaningful portion of page width; then it reads the left column top-to-bottom followed by the right column. This avoids the common interleaving problem in two-column resumes. Decorative sidebars, full-width headings, tables, and uneven layouts can still make this heuristic unreliable, so the parser falls back to pdfplumber's raw text order when it is not confident.

## OCR fallback

pdfplumber is attempted first, with PyMuPDF also used for layout-aware extraction. If the selected embedded text is under 50 characters, each page is rendered at 300 DPI and passed to Tesseract through Pillow. OCR output under 20 characters results in a failed parse with a reason rather than a crash. Tesseract itself must be installed and available on the system path for OCR to work; otherwise the resume is safely marked for manual review.

## Unstructured skill extraction

Skills are found across the entire extracted resume text using a fixed canonical vocabulary and alias patterns, so project and experience descriptions contribute evidence even without a Skills heading. Boundary-aware matching normalizes variants such as `reactjs` and `react.js`. It can miss niche technologies, unusual misspellings, skills represented only by logos, and scanned text that OCR reads incorrectly; the vocabulary is intentionally editable in `skills_vocab.py`.

## Parse quality and confidence

Clean parses require the core identity, education, CGPA, and skill evidence. Partial parses state which fields were unavailable and cap confidence at Medium, regardless of computed score. Failed parses never receive a score or ranking position; they remain visible in every JD output with a manual-review flag. This keeps scoring transparent without treating uncertain extraction as reliable evidence.
