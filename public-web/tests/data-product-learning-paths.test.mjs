import assert from "node:assert/strict";
import test from "node:test";
import { papers } from "../src/researchCatalog.js";

const titlesFor = (datasetId) => papers
  .filter((paper) => paper.related.datasets?.includes(datasetId))
  .map((paper) => paper.title);

test("reviewed data-product reading paths are explicit and source-specific", () => {
  const expectations = {
    "cn-equity-minute": [
      "Modeling and Forecasting Realized Volatility",
      "Intraday Information Efficiency on the Chinese Equity Market",
    ],
    "cn-pit-fundamentals": [
      "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?",
      "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers",
    ],
    "cn-company-actions": ["Event Studies in Economics and Finance"],
    "cn-announcements": [
      "Event Studies in Economics and Finance",
      "The Information Content of Forward-Looking Statements in Corporate Filings—A Naïve Bayesian Machine Learning Approach",
    ],
    "cn-news-flashes": [
      "Giving Content to Investor Sentiment: The Role of Media in the Stock Market",
      "Media Coverage and the Cross-section of Stock Returns",
    ],
    "cn-ownership-holdings": ["Corporate Ownership Around the World"],
    "cn-index-constituents": ["CSI 300 Index Methodology"],
    "us-notable-investor-13f": ["Form 13F: Official Filing Guidance and EDGAR Data Access"],
  };

  for (const [datasetId, expectedTitles] of Object.entries(expectations)) {
    const titles = titlesFor(datasetId);
    for (const title of expectedTitles) assert.ok(titles.includes(title), `${datasetId}: ${title}`);
  }
});

test("alternative-data categories do not inherit unrelated reading paths", () => {
  for (const datasetId of ["global-pizza-index", "global-foot-traffic", "global-hiring-index"]) {
    assert.deepEqual(titlesFor(datasetId), [], datasetId);
  }
});
