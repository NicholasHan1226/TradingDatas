/* A股事件日历 — 数据驱动渲染器。
 * 读取同目录 calendar-data.json。存档构建：不部署、不接实时接口。
 * td-v1 事件数据管道恢复后，用管道重新生成 JSON，本页无需改动即可呈现。 */
(function () {
  "use strict";
  var DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var now = new Date();
  var todayISO = now.getFullYear() + "-" +
    ("0" + (now.getMonth() + 1)).slice(-2) + "-" + ("0" + now.getDate()).slice(-2);

  /* ---------- 头部：市场环境 / 说明 / 摘要卡 / 图例 ---------- */
  function renderHeader(d) {
    if (d.regime && d.regime.label) {
      var rg = document.getElementById("regime");
      rg.hidden = false;
      rg.innerHTML = '<span class="dot"></span>当前市场环境:<b>' +
        esc(d.regime.label) + '</b>&nbsp;<span class="num">' + esc(d.regime.note || "") + "</span>";
    }
    document.getElementById("meta").innerHTML =
      esc(d.meta || "") + (d.generated_at ? ' · 快照生成 <span class="num">' + esc(d.generated_at) + "</span>" : "");

    var cards = document.getElementById("cards");
    if (d.summary_cards && d.summary_cards.length) {
      cards.hidden = false;
      d.summary_cards.forEach(function (c) {
        cards.appendChild(el("div", "card",
          '<b>' + esc(c.value) + "</b><span>" + esc(c.label) + "</span>"));
      });
    }

    var lg = document.getElementById("legend");
    lg.hidden = false;
    lg.innerHTML =
      '<span class="lg"><i class="sw" style="background:var(--accent)"></i>解禁 ≥5% 大额档</span>' +
      '<span class="lg"><i class="sw" style="background:color-mix(in srgb,var(--accent) 55%,transparent)"></i>解禁 1–3%</span>' +
      '<span class="lg"><i class="sw" style="background:var(--chip1)"></i>解禁 &lt;1% 小额</span>' +
      '<span class="lg"><i class="sw" style="background:var(--ep)"></i>财报·预增组</span>' +
      '<span class="lg"><i class="sw" style="background:var(--en)"></i>财报·预减组</span>' +
      '<span class="lg"><i class="sw" style="border-style:dashed;background:none"></i>LPR / 未匹配</span>' +
      '<span class="lg">色条 = 当日最强事件 · 点击日期看完整名单与历史结论</span>';
  }

  /* ---------- 单个日期格 ---------- */
  function cellHTML(day, rec, isWeekend) {
    var chips = (rec.chips || []).map(function (c) {
      return '<span class="ec ' + esc(c.cls) + '"><span class="s">' + esc(c.code) +
        '</span><span class="r">' + esc(c.dir) + "</span></span>";
    }).join("");
    var more = rec.more ? '<span class="more">还有 ' + rec.more + " 条</span>" : "";
    var cline = rec.count_line ? '<span class="c">' + esc(rec.count_line) + "</span>" : "";
    var isToday = day === todayISO;
    var cls = "cell " + (rec.tier || "m1") + " has" + (isWeekend ? " we" : "") + (isToday ? " today" : "");
    return '<button type="button" class="' + cls + '" data-day="' + day + '" aria-expanded="false">' +
      '<span class="dnum"><span class="n">' + Number(day.slice(8)) + "</span>" + cline + "</span>" +
      '<span class="echips">' + chips + "</span>" + more + "</button>";
  }

  /* ---------- 当日明细表 ---------- */
  function dowCN(iso) {
    var dt = new Date(iso + "T12:00:00+08:00");
    return DOW[(dt.getDay() + 6) % 7];
  }
  function detailHTML(day, rec) {
    var evs = rec.events || [];
    var rows = evs.map(function (e) {
      var chip = e.chip_text ? '<span class="chip ' + esc(e.chip_cls) + '">' + esc(e.chip_text) + "</span> " : "";
      var stat = "";
      if (e.stat) {
        var parts = e.stat.split("·");
        stat = '<span class="stat"><span class="' + esc(e.direction || "") + '">' + esc(parts[0].trim()) +
          "</span>" + (parts.length > 1 ? " · " + esc(parts.slice(1).join("·").trim()) : "") + "</span>";
      }
      return "<tr><td class=\"code\">" + esc(e.code) + '</td><td class="nm">' + esc(e.name) + "</td>" +
        '<td class="holder">' + esc(e.party || "") + "</td>" +
        '<td class="ratio">' + esc(e.ratio) + "</td><td>" + chip + stat + "</td></tr>";
    }).join("");
    var head = "<tr><td class=\"code\">代码</td><td class=\"nm\">公司</td><td>事项 / 解禁方</td>" +
      '<td class="ratio">占比 / 幅度</td><td>该档历史结论</td></tr>';
    return '<div class="daydetail"><div class="dtitle">' + day.slice(5) + " " + dowCN(day) +
      "<small> · 共 " + evs.length + " 条明细</small></div>" +
      '<div class="scrollwrap"><table class="evtable">' + head + rows + "</table></div></div>";
  }

  /* ---------- 月网格（周一开头） ---------- */
  function monthGrid(y, m, days) {
    var lead = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
    var dim = new Date(Date.UTC(y, m, 0)).getUTCDate();
    var out = DOW.map(function (d) { return '<div class="dowh">' + d + "</div>"; }).join("");
    var i;
    for (i = 0; i < lead; i++) out += '<div class="cell empty"></div>';
    for (var dd = 1; dd <= dim; dd++) {
      var iso = y + "-" + ("0" + m).slice(-2) + "-" + ("0" + dd).slice(-2);
      var wd = (lead + dd - 1) % 7;
      out += days[iso]
        ? cellHTML(iso, days[iso], wd >= 5)
        : '<div class="cell' + (wd >= 5 ? " we" : "") + '"><span class="dnum"><span class="n">' + dd + "</span></span></div>";
    }
    var pad = (7 - ((lead + dim) % 7)) % 7;
    for (i = 0; i < pad; i++) out += '<div class="cell empty"></div>';
    return out;
  }

  /* ---------- 全部月份；当年之后的所有年份折进一个折叠块 ---------- */
  function renderMonths(data) {
    var host = document.getElementById("months");
    var monthKeys = Object.keys(data.months).sort();
    var curYear = String(now.getFullYear());
    var openKeys = monthKeys.filter(function (k) { return k.slice(0, 4) <= curYear; });
    var foldKeys = monthKeys.filter(function (k) { return k.slice(0, 4) > curYear; });

    function buildMonth(mk, target) {
      var y2 = Number(mk.slice(0, 4)), m2 = Number(mk.slice(5));
      var sec = el("section", "month");
      sec.innerHTML = '<div class="mh"><h2 class="serif">' + y2 + " 年 " + m2 + ' 月</h2><small>' +
        esc(data.months[mk]) + "</small></div>" +
        '<div class="cal">' + monthGrid(y2, m2, data.days) + "</div>";
      target.appendChild(sec);
    }

    openKeys.forEach(function (mk) { buildMonth(mk, host); });

    if (foldKeys.length) {
      var fold = el("details", "yearfold");
      var yFrom = foldKeys[0].slice(0, 4), yTo = foldKeys[foldKeys.length - 1].slice(0, 4);
      var label = yFrom === yTo ? yFrom + " 年" : yFrom + "–" + yTo + " 年";
      var evCount = foldKeys.reduce(function (acc, mk) {
        var pre = mk + "-";
        return acc + Object.keys(data.days).filter(function (d) { return d.indexOf(pre) === 0; }).length;
      }, 0);
      fold.innerHTML = "<summary><h2 class=\"serif\">" + label + "</h2>" +
        '<span class="yc">共 ' + foldKeys.length + " 个月 · " + evCount + " 个事件日</span>" +
        '<span class="hint">点击展开</span></summary><div class="ybody"></div>';
      var body = fold.querySelector(".ybody");
      foldKeys.forEach(function (mk) { buildMonth(mk, body); });
      host.appendChild(fold);
    }

    /* 点击日期 → 本月内展开唯一一张明细表；再点一次收起 */
    host.addEventListener("click", function (ev) {
      var b = ev.target.closest("button.cell[data-day]");
      if (!b) return;
      var sec = b.closest("section.month");
      if (!sec) return;
      var wasSel = b.classList.contains("sel");
      sec.querySelectorAll("button.cell.sel").forEach(function (x) {
        x.classList.remove("sel"); x.setAttribute("aria-expanded", "false");
      });
      sec.querySelectorAll(".daydetail").forEach(function (dd) { dd.remove(); });
      if (wasSel) return;
      b.classList.add("sel"); b.setAttribute("aria-expanded", "true");
      var frag = el("div");
      frag.innerHTML = detailHTML(b.dataset.day, data.days[b.dataset.day] || { events: [] });
      sec.appendChild(frag.firstChild);
    });
  }

  /* ---------- 载入 ---------- */
  fetch("calendar-data.json", { cache: "no-cache" }).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (data) {
    if (!data || !data.days || !Object.keys(data.days).length) throw new Error("数据为空");
    document.getElementById("status").hidden = true;
    renderHeader(data);
    renderMonths(data);
    document.getElementById("footer").hidden = false;
  }).catch(function (e) {
    var st = document.getElementById("status");
    st.textContent = "数据未接入：无法读取日历数据文件（" + e.message +
      "）。本页为存档构建，事件数据管道恢复后重新生成数据文件即可呈现。";
  });
})();
