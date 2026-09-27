import hljs from "highlight.js/lib/core";
import sql from "highlight.js/lib/languages/sql";
import { useMemo } from "react";

hljs.registerLanguage("sql", sql);

export function SqlCode({ code }: { code: string }) {
  const html = useMemo(() => hljs.highlight(code, { language: "sql" }).value, [code]);
  return (
    <pre className="sql-code">
      <code dangerouslySetInnerHTML={{ __html: html }} />
    </pre>
  );
}
