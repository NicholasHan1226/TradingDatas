import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { preparationTutorials } from "../src/preparationTutorials.js";
import { tutorialCode, tutorialExamples } from "../src/tutorialExamples.js";

const functionNames = { "adjusted-price-series": "adjust_prices", "pit-fundamentals-panel": "select_as_of", "company-event-timeline": "align_events" };
const markdown = (source, id) => ({ cell_type: "markdown", id, metadata: {}, source: source.split(/(?<=\n)/) });
const codeCell = (source, id) => ({ cell_type: "code", id, metadata: {}, execution_count: null, outputs: [], source: source.split(/(?<=\n)/) });

export function tutorialDownloadFiles(id) {
  const tutorial = preparationTutorials[id], example = tutorialExamples[id];
  if (!tutorial || !example) throw new Error("unknown_tutorial");
  const python = readFileSync(new URL(`./tutorial-python/${id}.py`, import.meta.url), "utf8");
  const expected = example.execute(...example.args);
  const input = { version: 1, tutorial: id, identity: "synthetic", args: example.args, expected };
  const files = { "inputs.json": JSON.stringify(input, null, 2) + "\n", "example.mjs": tutorialCode(id) + "\n" };
  for (const locale of ["zh", "en"]) {
    const zh = locale === "zh";
    const cells = [
      markdown(`# ${tutorial.title[locale]}\n\n${zh ? "## 目标" : "## Goal"}\n\n${tutorial.goal[locale]}\n\n${zh ? "本文件使用虚构教学数据，不是论文复现或生产数据。" : "This notebook uses synthetic teaching data, not a paper replication or production observations."}`, "goal"),
      markdown(zh ? "## 准备\n\n使用 Python 3.10+ 内核，按顺序运行全部单元格。计算仅依赖标准库，无需密钥、联网或额外数据文件。可在已有的 Jupyter 环境中打开。\n\n输入已内嵌，与同目录 inputs.json 内容一致；可在下一个单元格中修改 args 试验。时间与单位必须显式保留。" : "## Setup\n\nUse a Python 3.10+ kernel and run all cells in order. Computation uses only the standard library, without keys, networking or extra data files. Open in an existing Jupyter environment.\n\nEmbedded inputs match inputs.json in the same download directory. Edit args in the next cell to experiment; preserve explicit times and units.", "setup"),
      codeCell(`import json\n\n# Synthetic inputs; no credentials or network access.\nbundle = json.loads(${JSON.stringify(JSON.stringify(input))})\nargs = bundle["args"]\nexpected = bundle["expected"]\nprint(json.dumps(args, ensure_ascii=False, indent=2))`, "inputs"),
      markdown(`## ${zh ? "步骤" : "Steps"}\n\n${tutorial.steps.map((step, i) => `### ${i + 1}. ${step.title[locale]}\n\n${step.body[locale]}`).join("\n\n")}\n\n### ${zh ? "方法与假设" : "Method and assumptions"}\n\n${tutorial.pitfalls.map((item) => `- ${item[locale]}`).join("\n")}`, "method"),
      codeCell(python, "implementation"),
      markdown(`### ${zh ? "运行小样本" : "Run the sample"}\n\n${tutorial.expected[locale]}`, "run-label"),
      codeCell(`result = ${functionNames[id]}(*args)\nprint(json.dumps(result, ensure_ascii=False, indent=2))`, "run"),
      markdown(zh ? "## 检查\n\n将每一行与网页示例的预期输出比较。修改输入后，断言失败可能正是预期结果：先解释差异，不要直接删除验证。" : "## Checks\n\nCompare every row with the browser example's expected output. After editing inputs, a failed assertion may be expected: explain the difference before changing the check.", "checks-label"),
      codeCell(`assert result == expected, "Output differs from the reference synthetic example"\nassert bundle["identity"] == "synthetic"\nprint(${JSON.stringify(zh ? "通过：结果与网页虚构示例一致。" : "Passed: output matches the synthetic browser example.")})`, "checks"),
      markdown(`## ${zh ? "下一步" : "Next steps"}\n\n${zh ? "真实数据须先通过已认证 GET /v1/catalog 核对权限、字段、schema_major、窗口与来源，再按实际合同映射。这里列出的是候选输入身份，不保证可用或历史完整。不要把 API as_of 当作历史财报版本。真实输入替换后须重新验证；不要沿用这份小样本的通过结论。" : "Before real data, confirm grants, fields, schema_major, windows and provenance using authenticated GET /v1/catalog, then map the actual contract. Candidate IDs below do not guarantee availability or historical completeness. API as_of is not a historical filing-version guarantee. Validate again after substituting real inputs; the synthetic pass does not transfer."}\n\n${tutorial.datasetIds.map((item) => `- \`${item}\``).join("\n")}\n\n### ${zh ? "参考资料" : "References"}\n\n${tutorial.sources.map((item) => `- [${item.label[locale]}](${item.url})`).join("\n")}\n\n[${zh ? "返回教程" : "Back to tutorial"}](https://tradingdatas.com/recipes/${id}/)`, "next"),
    ];
    files[`tutorial-${locale}.ipynb`] = JSON.stringify({ cells, metadata: { kernelspec: { display_name: "Python 3", language: "python", name: "python3" }, language_info: { name: "python", version: "3.10" } }, nbformat: 4, nbformat_minor: 5 }, null, 2) + "\n";
  }
  return files;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  for (const id of Object.keys(preparationTutorials)) {
    const directory = fileURLToPath(new URL(`../dist/client/downloads/research/${id}/`, import.meta.url));
    mkdirSync(directory, { recursive: true });
    for (const [name, content] of Object.entries(tutorialDownloadFiles(id))) writeFileSync(path.join(directory, name), content);
  }
  console.log("Prepared 3 synthetic input files, 3 JavaScript examples and 6 localized Python notebooks.");
}
