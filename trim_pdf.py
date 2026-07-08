from pypdf import PdfReader, PdfWriter

reader = PdfReader("Allied_Trust_HO3.pdf")
writer = PdfWriter()

# Add all pages EXCEPT pages 4 and 5
# PyPDF uses 0-based indexing, so page 4 = index 3, page 5 = index 4
for i, page in enumerate(reader.pages):
    if i not in [3, 4]:
        writer.add_page(page)

with open("Allied_Trust_HO3_trimmed.pdf", "wb") as f:
    writer.write(f)

print("Done. Pages removed: 4 and 5")
print("Original pages:", len(reader.pages))
print("New pages:", len(writer.pages))
