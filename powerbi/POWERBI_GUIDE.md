# Building the Infection Lab dashboard in Power BI

The browser map shows *how* you discovered music. This dashboard answers the
analytical questions: how fast you discover, who mattered most, and which
discoveries stuck.

You need Power BI Desktop (free, Windows). On a Mac, use the browser version at
app.powerbi.com: upload the CSV, create a report, and add the measures in the model view.

## 1. Export the data

```bash
python infection_lab.py --data path/to/history --out data/infection_lab.html --csv --no-open
```

This writes `data/infection_lab_nodes.csv` and `data/infection_lab_edges.csv`.
To practise first, use `infection_lab_demo_nodes.csv` (synthetic data).

To refresh later: rerun the command, then press Refresh in Power BI.

## 2. Load and shape

1. Home > Get data > Text/CSV > `..._nodes.csv` > Transform data.
2. Check column types: `first_heard` = **Date**, `is_patient_zero` = **True/False**,
   everything numeric = **Whole number**.
3. Rename the query to `Artists`. Close & Apply.

`..._edges.csv` is optional. Load it as `Edges` only if you want a source/target table.

## 3. Calendar table

Modeling > New table:

```dax
Calendar =
ADDCOLUMNS(
    CALENDAR(MIN(Artists[first_heard]), MAX(Artists[first_heard])),
    "Month", DATE(YEAR([Date]), MONTH([Date]), 1)
)
```

- Table tools > **Mark as date table** (use `Date`).
- Format `Month` as `mmm yy`.
- Model view: drag `Calendar[Date]` onto `Artists[first_heard]` (one to many).

## 4. Measures

Create them in a table called `Measures` (Enter data > empty table), or on `Artists`.

```dax
Artists Discovered = COUNTROWS(Artists)

Patient Zeros =
CALCULATE(COUNTROWS(Artists), Artists[is_patient_zero] = TRUE())

Spontaneous Finds % = DIVIDE([Patient Zeros], [Artists Discovered])

Biggest Reach = MAX(Artists[total_reach])

Top Influencer =
VAR best = MAX(Artists[total_reach])
RETURN CONCATENATEX(FILTER(Artists, Artists[total_reach] = best), Artists[artist], ", ")

Sticky Artists =
CALCULATE(COUNTROWS(Artists), Artists[plays_first_7d] >= 5)

Stickiness % = DIVIDE([Sticky Artists], [Artists Discovered])

Cumulative Artists =
CALCULATE(
    [Artists Discovered],
    FILTER(ALL(Calendar[Date]), Calendar[Date] <= MAX(Calendar[Date]))
)
```

"Sticky" means 5 or more plays of that artist in their first 7 days. Change the
threshold to taste, and say what it is in your post.

## 5. Theme and canvas

- View > Themes > Browse for themes > `infection_lab_theme.json`.
- View > Page view > Page size: keep 16:9 (1280 x 720). It exports cleanly for LinkedIn.

## 6. Layout (1280 x 720)

| Zone | Visual | Fields |
|---|---|---|
| Top left | Text box title: "How I discover music" | |
| Top right | Slicer, style Between | `Calendar[Date]` |
| Row of 4 cards | Card | `Artists Discovered`, `Patient Zeros`, `Top Influencer`, `Stickiness %` |
| Middle left (wide) | Line and clustered column | X `Calendar[Month]` (turn off date hierarchy), columns `Artists Discovered`, line `Cumulative Artists` |
| Middle right | Clustered bar | Y `Artists[artist]`, X `Artists[total_reach]`; visual filter Top N = 10 by `total_reach` |
| Bottom left | Scatter | X `plays_first_7d` (Don't summarize), Y `total_reach` (Don't summarize), Details `artist`, Size `total_plays`, Legend `is_patient_zero` |
| Bottom right | Image | Screenshot of the browser map (Insert > Image) |

Set Alt text on every visual (Format > General > Alt text). It helps readers and
it is a quality signal in a portfolio piece.

## 7. How to read it (for your caption)

- **Total reach**: artists downstream of this one in your discovery tree. It rewards
  being early in long listening chains, so it is partly "being around at the right time".
- **Plays in first 7 days**: this artist's own plays after you found them. A high
  value means you went deep straight away.
- Reach vs stickiness separates gateway artists (high reach, low stickiness)
  from artists you simply fell for (low reach, high stickiness).

## 8. Export for LinkedIn

- File > Export > PDF (good for a document/carousel post), or
- screenshot the page at 100% zoom (good for a single image).
- Avoid "Publish to web": it makes the report public.
