// osascript -l JavaScript combine.js spec.json out.pdf : склейка PDF, закладки, ссылки с индексной страницы (PDFKit)
ObjC.import('PDFKit'); ObjC.import('Foundation');
function run(argv) {
  const spec = JSON.parse(ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null)));
  const out = $.PDFDocument.alloc.init;
  const keep = [];
  const starts = [];
  let n = 0;
  for (const f of spec.files) {
    const d = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(f.pdf));
    keep.push(d);
    starts.push(n);
    const cnt = d.pageCount;
    for (let i = 0; i < cnt; i++) { out.insertPageAtIndex(d.pageAtIndex(i), n); n++; }
  }
  // закладки
  const root = $.PDFOutline.alloc.init;
  let ri = 0;
  spec.files.forEach((f, k) => {
    if (!f.title) return;
    const mk = (label, page) => {
      const it = $.PDFOutline.alloc.init;
      it.label = label;
      it.destination = $.PDFDestination.alloc.initWithPageAtPoint(out.pageAtIndex(page), $.NSMakePoint(0, 800));
      return it;
    };
    const top = mk(f.title, starts[k]);
    root.insertChildAtIndex(top, ri++);
    let last = null, ci = 0, cj = 0;
    for (const [lvl, text, page] of f.toc) {
      const it = mk(text, starts[k] + page - 1);
      if (lvl === 1) { top.insertChildAtIndex(it, ci++); last = it; cj = 0; }
      else if (last) { last.insertChildAtIndex(it, cj++); }
    }
  });
  out.outlineRoot = root;
  // ссылки на индексной странице
  spec.files.forEach((f, k) => {
    if (!f.title) return;
    const sels = ObjC.unwrap(out.findStringWithOptions(f.title, 0));
    if (!sels || !sels.length) return;
    const sel = sels[0];
    const pages = sel.pages;
    const pg = pages.objectAtIndex(0);
    const b = sel.boundsForPage(pg);
    const a = $.PDFAnnotation.alloc.initWithBoundsForTypeWithProperties(b, 'Link', $());
    a.destination = $.PDFDestination.alloc.initWithPageAtPoint(out.pageAtIndex(starts[k]), $.NSMakePoint(0, 800));
    pg.addAnnotation(a);
  });
  out.writeToFile(argv[1]);
  return JSON.stringify({ pages: n, starts: starts.map((s) => s + 1) });
}
