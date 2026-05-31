// Data model for the /data JSON the Python backend emits. Property names match
// the JSON exactly, so System.Text.Json binds them with no attributes. The
// renderer is the ONLY consumer - the backend stays rendering-agnostic.

using System.Collections.Generic;

class Snapshot
{
    public double t { get; set; }
    public List<Hmi> hmis { get; set; }
}

class Hmi
{
    public string id { get; set; }
    public string title { get; set; }
    public string subtitle { get; set; }
    public List<Channel> channels { get; set; }
    public List<Note> notes { get; set; }
    public Dictionary<string, string> header { get; set; }
    public string state { get; set; }
    public string state_sev { get; set; }
}

class Channel
{
    public string key { get; set; }
    public string label { get; set; }
    public string sub { get; set; }
    public string value { get; set; }
    public string unit { get; set; }
    public double fill { get; set; }     // 0..100
    public string readout { get; set; }
    public string sev { get; set; }      // ok | warn | alert | info
    public string status { get; set; }
}

class Note
{
    public string sev { get; set; }
    public string text { get; set; }
    public string tag { get; set; }
}
