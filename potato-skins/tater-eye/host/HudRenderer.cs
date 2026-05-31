// HudRenderer - draws the dashboard with GDI+ (System.Drawing). Same visual
// language as the old WebView2/CSS front-end (slate panels, hairline rules,
// big tabular numerics, semantic accents, diagnostic stream) but as native
// draw calls: ~0 VRAM, GPU idles between the 0.5 Hz repaints.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;

static class Pal
{
    public static readonly Color Ink = C(0x070a0d);
    public static readonly Color Panel = C(0x121821);
    public static readonly Color PanelHead = C(0x18202a);
    public static readonly Color Rule = Color.FromArgb(16, 255, 255, 255);
    public static readonly Color Rule2 = Color.FromArgb(30, 255, 255, 255);
    public static readonly Color Text = C(0xe9ecf2);
    public static readonly Color Text2 = C(0xa4adb8);
    public static readonly Color Text3 = C(0x5b6471);
    public static readonly Color Text4 = C(0x3a424b);
    public static readonly Color Blue = C(0x4a9eff);
    public static readonly Color Amber = C(0xf4a020);
    public static readonly Color Red = C(0xe8424d);
    public static readonly Color RedHot = C(0xff5862);
    public static readonly Color Green = C(0x3fb950);
    public static readonly Color Track = Color.FromArgb(14, 255, 255, 255);

    static Color C(int rgb) => Color.FromArgb((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255);

    public static Color Sev(string s) => s switch
    {
        "ok" => Green, "warn" => Amber, "alert" => RedHot, "info" => Blue, _ => Text3
    };
    public static Color BarSev(string s) => s switch
    {
        "warn" => Amber, "alert" => Red, _ => Blue
    };
}

class Fonts
{
    readonly string _mono, _sans;
    readonly Dictionary<string, Font> _cache = new();

    public Fonts()
    {
        var have = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using (var ifc = new InstalledFontCollection())
            foreach (var f in ifc.Families) have.Add(f.Name);
        _mono = Pick(have, "Consolas", "JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas");
        _sans = Pick(have, "Segoe UI", "Manrope", "Segoe UI Variable Display", "Segoe UI");
    }

    static string Pick(HashSet<string> have, string fallback, params string[] prefs)
    {
        foreach (var p in prefs) if (have.Contains(p)) return p;
        return fallback;
    }

    Font Get(string fam, float px, FontStyle st)
    {
        string k = fam + px + (int)st;
        if (!_cache.TryGetValue(k, out var f))
            _cache[k] = f = new Font(fam, px, st, GraphicsUnit.Pixel);
        return f;
    }
    public Font Mono(float px, FontStyle st = FontStyle.Regular) => Get(_mono, px, st);
    public Font Sans(float px, FontStyle st = FontStyle.Regular) => Get(_sans, px, st);
}

class HudRenderer
{
    readonly Fonts F = new();

    const int PAD = 24, GAP = 20, HEAD_H = 64;

    public void Render(Graphics g, int w, int h, Snapshot snap)
    {
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        g.InterpolationMode = InterpolationMode.HighQualityBilinear;
        using (var bg = new SolidBrush(Pal.Ink)) g.FillRectangle(bg, 0, 0, w, h);

        if (snap?.hmis == null || snap.hmis.Count == 0)
        {
            DrawCenter(g, "ESTABLISHING TELEMETRY LINK", F.Mono(13), Pal.Text3, w, h);
            return;
        }

        int n = snap.hmis.Count;
        int cols = n <= 1 ? 1 : 2;
        int rows = (n + cols - 1) / cols;
        int pw = (w - 2 * PAD - (cols - 1) * GAP) / cols;
        int ph = (h - 2 * PAD - (rows - 1) * GAP) / rows;

        for (int i = 0; i < n; i++)
        {
            int c = i % cols, r = i / cols;
            int x = PAD + c * (pw + GAP);
            int y = PAD + r * (ph + GAP);
            DrawPanel(g, x, y, pw, ph, snap.hmis[i]);
        }
    }

    void DrawPanel(Graphics g, int x, int y, int pw, int ph, Hmi hmi)
    {
        using (var b = new SolidBrush(Pal.Panel)) g.FillRectangle(b, x, y, pw, ph);
        bool alert = hmi.state_sev == "alert" || HasAlert(hmi);

        // ---- header ----
        using (var hb = new SolidBrush(Pal.PanelHead)) g.FillRectangle(hb, x, y, pw, HEAD_H);
        // diamond mark
        var mc = alert ? Pal.Red : Pal.Blue;
        DrawDiamond(g, x + 18, y + HEAD_H / 2, 9, mc);
        float tx = x + 42;
        DrawStr(g, (hmi.title ?? "").ToUpperInvariant(), F.Sans(15, FontStyle.Bold), Pal.Text, tx, y + 14);
        DrawStr(g, hmi.subtitle ?? "", F.Mono(10), Pal.Text3, tx, y + 36);
        DrawHeaderRight(g, x, y, pw, hmi);
        Hairline(g, x, y + HEAD_H, x + pw, y + HEAD_H);

        // ---- regions ----
        int streamH = (int)Math.Min(ph * 0.34, 40 + (hmi.notes?.Count ?? 0) * 30 + 38);
        int chTop = y + HEAD_H;
        int chH = ph - HEAD_H - streamH;
        var chans = hmi.channels ?? new List<Channel>();
        if (chans.Count > 0)
        {
            float rh = chH / (float)chans.Count;
            for (int i = 0; i < chans.Count; i++)
                DrawChannel(g, x, chTop + i * rh, pw, rh, chans[i], i, i == 0);
        }
        DrawStream(g, x, y + ph - streamH, pw, streamH, hmi);

        // panel border last (crisp edge)
        using (var pen = new Pen(Pal.Rule)) g.DrawRectangle(pen, x, y, pw - 1, ph - 1);
    }

    void DrawChannel(Graphics g, float x, float y, float w, float h, Channel ch, int idx, bool first)
    {
        var sev = ch.sev ?? "ok";
        // row accent for warn/alert
        if (sev == "warn" || sev == "alert")
        {
            var ac = sev == "alert" ? Pal.Red : Pal.Amber;
            using (var grad = new LinearGradientBrush(
                new RectangleF(x, y, w * 0.6f, h),
                Color.FromArgb(sev == "alert" ? 28 : 18, ac), Color.FromArgb(0, ac),
                LinearGradientMode.Horizontal))
                g.FillRectangle(grad, x, y, w * 0.6f, h);
            using (var ab = new SolidBrush(ac))
                g.FillRectangle(ab, x, y, sev == "alert" ? 4 : 3, h);
        }
        if (!first) Hairline(g, x, y, x + w, y);

        float pad = 18, gap = 18, idW = 40, statusW = 104;
        float idX = x + pad;
        float metaX = idX + idW + gap;
        float statusX = x + w - pad - statusW;
        float readRight = statusX - gap;
        float midW = readRight - metaX;
        float metaW = midW * 0.40f;
        float readX = metaX + metaW + gap;
        float cy = y + h / 2;

        // id column: "C-0x" + dot
        DrawStr(g, "C-" + (idx + 1).ToString("00"), F.Mono(10), Pal.Text3, idX, cy - 16);
        DrawDot(g, idX + 3, cy + 6, 4, Pal.Sev(sev));

        // meta: label + sub
        DrawStrEllipsis(g, (ch.label ?? "").ToUpperInvariant(), F.Sans(15, FontStyle.Bold), Pal.Text,
            metaX, cy - 17, metaW);
        DrawStrEllipsis(g, ch.sub ?? "", F.Mono(10), Pal.Text3, metaX, cy + 4, metaW);

        // readout: big value + unit, readout text right-aligned, bar below
        var valColor = sev == "alert" ? Pal.RedHot : sev == "warn" ? Pal.Amber : Pal.Text;
        var vfont = F.Mono(30, FontStyle.Bold);
        float vy = cy - 24;
        float vw = MeasureW(g, ch.value ?? "", vfont);
        DrawStr(g, ch.value ?? "", vfont, valColor, readX, vy);
        if (!string.IsNullOrEmpty(ch.unit))
            DrawStr(g, ch.unit, F.Mono(13), Pal.Text3, readX + vw + 4, vy + 14);
        DrawStrRight(g, ch.readout ?? "", F.Mono(11), Pal.Text2, readRight, cy - 18);

        // bar
        float barY = cy + 14, barH = 5;
        using (var tb = new SolidBrush(Pal.Track)) g.FillRectangle(tb, readX, barY, readRight - readX, barH);
        float fill = (float)Math.Max(0, Math.Min(100, ch.fill)) / 100f;
        if (fill > 0)
            using (var fb = new SolidBrush(Pal.BarSev(sev)))
                g.FillRectangle(fb, readX, barY, (readRight - readX) * fill, barH);
        using (var pen = new Pen(Pal.Rule)) g.DrawRectangle(pen, readX, barY, readRight - readX, barH);

        // status word
        DrawStrRight(g, (ch.status ?? "").ToUpperInvariant(), F.Mono(10, FontStyle.Bold),
            Pal.Sev(sev), x + w - pad, cy - 6);
    }

    void DrawStream(Graphics g, float x, float y, float w, float h, Hmi hmi)
    {
        using (var hb = new SolidBrush(Pal.PanelHead)) g.FillRectangle(hb, x, y, w, 30);
        Hairline(g, x, y, x + w, y);
        DrawDot(g, x + 18, y + 15, 4, Pal.Green);
        DrawStr(g, "DIAGNOSTIC STREAM", F.Sans(10, FontStyle.Bold), Pal.Text, x + 28, y + 9);
        int a = 0, wn = 0;
        foreach (var nt in hmi.notes ?? new List<Note>())
        { if (nt.sev == "alert") a++; else if (nt.sev == "warn") wn++; }
        string ts = DateTime.Now.ToString("HH:mm:ss");
        DrawStrRight(g, $"{ts}  {a}A {wn}W", F.Mono(9.5f), Pal.Text3, x + w - 16, y + 10);

        float ly = y + 30;
        float rowH = 30;
        foreach (var nt in hmi.notes ?? new List<Note>())
        {
            if (ly + rowH > y + h) break;
            Hairline(g, x, ly, x + w, ly);
            var sc = Pal.Sev(nt.sev);
            DrawStr(g, ts, F.Mono(10), Pal.Text4, x + 16, ly + 9);
            // sev chip
            var chipRect = new RectangleF(x + 96, ly + 7, 64, 16);
            using (var pen = new Pen(sc)) g.DrawRectangle(pen, chipRect.X, chipRect.Y, chipRect.Width, chipRect.Height);
            DrawStrRectCenter(g, (nt.sev ?? "").ToUpperInvariant(), F.Mono(9, FontStyle.Bold), sc, chipRect);
            DrawStrEllipsis(g, nt.text ?? "", F.Mono(11.5f), Pal.Text, x + 174, ly + 8, w - 174 - 16);
            ly += rowH;
        }
    }

    void DrawHeaderRight(Graphics g, int x, int y, int pw, Hmi hmi)
    {
        float right = x + pw - 16;
        // LIVE pill
        string live = "LIVE";
        var lf = F.Mono(9.5f, FontStyle.Bold);
        float lw = MeasureW(g, live, lf);
        float pillW = lw + 26, pillH = 20;
        float pillX = right - pillW, pillY = y + (HEAD_H - pillH) / 2;
        using (var pen = new Pen(Pal.Rule)) g.DrawRectangle(pen, pillX, pillY, pillW, pillH);
        DrawDot(g, pillX + 10, pillY + pillH / 2, 3.5f, Pal.Green);
        DrawStr(g, live, lf, Pal.Green, pillX + 17, pillY + 5);
        right = pillX - 18;

        // KPI pairs, right to left
        if (hmi.header == null) return;
        var items = new List<KeyValuePair<string, string>>(hmi.header);
        for (int i = items.Count - 1; i >= 0; i--)
        {
            var kf = F.Mono(8.5f); var vf = F.Mono(12, FontStyle.Bold);
            float kw = MeasureW(g, items[i].Key.ToUpperInvariant(), kf);
            float vw = MeasureW(g, items[i].Value ?? "", vf);
            float colW = Math.Min(180, Math.Max(kw, vw));
            float colX = right - colW;
            DrawStrRight(g, items[i].Key.ToUpperInvariant(), kf, Pal.Text4, right, y + 16);
            DrawStrRight(g, items[i].Value ?? "", vf, Pal.Text, right, y + 30);
            right = colX - 18;
            if (right < x + 220) break; // don't collide with title
        }
    }

    // ---- primitives ----
    static readonly StringFormat SfNoWrap = new StringFormat(StringFormatFlags.NoWrap)
    { Trimming = StringTrimming.EllipsisCharacter };

    void DrawStr(Graphics g, string s, Font f, Color c, float x, float y)
    {
        using var b = new SolidBrush(c);
        g.DrawString(s, f, b, x, y, StringFormat.GenericTypographic);
    }
    void DrawStrRight(Graphics g, string s, Font f, Color c, float right, float y)
    {
        float w = MeasureW(g, s, f);
        DrawStr(g, s, f, c, right - w, y);
    }
    void DrawStrEllipsis(Graphics g, string s, Font f, Color c, float x, float y, float maxW)
    {
        using var b = new SolidBrush(c);
        g.DrawString(s, f, b, new RectangleF(x, y, maxW, f.Height + 4), SfNoWrap);
    }
    void DrawStrRectCenter(Graphics g, string s, Font f, Color c, RectangleF r)
    {
        using var b = new SolidBrush(c);
        using var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
        g.DrawString(s, f, b, r, sf);
    }
    void DrawCenter(Graphics g, string s, Font f, Color c, int w, int h)
    {
        using var b = new SolidBrush(c);
        using var sf = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };
        g.DrawString(s, f, b, new RectangleF(0, 0, w, h), sf);
    }
    float MeasureW(Graphics g, string s, Font f)
        => g.MeasureString(s, f, PointF.Empty, StringFormat.GenericTypographic).Width;

    void Hairline(Graphics g, float x1, float y1, float x2, float y2)
    {
        using var pen = new Pen(Pal.Rule);
        g.DrawLine(pen, x1, y1, x2, y2);
    }
    void DrawDot(Graphics g, float cx, float cy, float r, Color c)
    {
        using var b = new SolidBrush(c);
        g.FillEllipse(b, cx - r, cy - r, r * 2, r * 2);
    }
    void DrawDiamond(Graphics g, float cx, float cy, float r, Color c)
    {
        var pts = new[] { new PointF(cx, cy - r), new PointF(cx + r, cy), new PointF(cx, cy + r), new PointF(cx - r, cy) };
        using var b = new SolidBrush(c);
        g.FillPolygon(b, pts);
    }

    static bool HasAlert(Hmi h)
    {
        if (h.notes != null) foreach (var n in h.notes) if (n.sev == "alert") return true;
        return false;
    }
}
