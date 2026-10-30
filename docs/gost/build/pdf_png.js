// osascript -l JavaScript pdf_png.js in.pdf outprefix first last : страницы PDF -> PNG (PDFKit)
ObjC.import('PDFKit'); ObjC.import('AppKit');
function run(argv) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  const a = parseInt(argv[2]), b = Math.min(parseInt(argv[3]), doc.pageCount);
  for (let i = a; i <= b; i++) {
    const img = doc.pageAtIndex(i - 1).thumbnailOfSizeForBox($.NSMakeSize(794, 1123), 0);
    const rep = $.NSBitmapImageRep.imageRepWithData(img.TIFFRepresentation);
    const png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $());
    png.writeToFileAtomically(argv[1] + '-' + i + '.png', true);
  }
  return doc.pageCount;
}
