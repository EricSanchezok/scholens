export function hasInvalidManualSvg(contents) {
  const svgTags = [...contents.matchAll(/<svg\b[^>]*>/gs)];
  const invalidSvg = svgTags.some((match) => {
    const tag = match[0];
    return (
      !/\bdata-visualization(?:=|\s|>)/.test(tag) ||
      !/\brole=["']img["']/.test(tag) ||
      !/\baria-(?:label|labelledby)=/.test(tag)
    );
  });
  return invalidSvg || /createElement\(\s*["']svg["']/.test(contents);
}
