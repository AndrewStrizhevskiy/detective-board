// osascript -l JavaScript pdf_pages.js in.pdf out.json : текст каждой страницы PDF (PDFKit)
ObjC.import('PDFKit'); ObjC.import('Foundation');
function run(argv) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  const n = doc.pageCount, out = [];
  for (let i = 0; i < n; i++) out.push(ObjC.unwrap(doc.pageAtIndex(i).string) || '');
  $(JSON.stringify(out)).writeToFileAtomicallyEncodingError(argv[1], true, $.NSUTF8StringEncoding, null);
  return n;
}
