// Home Assistant inputs: select calendar.abfallkalender and calendar.geburtstage.
// Set this image's time zone, a 366-day look-ahead, and Start at local midnight.
const events = [
  ...ha.calendarEvents("calendar.abfallkalender"),
  ...ha.calendarEvents("calendar.geburtstage")
]
  .filter(event => event.daysUntil >= 0)
  .sort((a, b) => a.daysUntil - b.daysUntil || a.start.localeCompare(b.start))
  .slice(0, 2);

function eventText(event) {
  if (!event) return "";
  if (event.daysUntil === 0) return `${event.summary}: Heute`;
  if (event.daysUntil === 1) return `${event.summary}: Morgen`;
  return `${event.summary}: in ${event.daysUntil} Tagen`;
}

screen.clear(palette.white);
for (let i = 0; i < events.length; i++) {
  screen.text(eventText(events[i]), {
    x: 24, y: 30 + i * 100, font: "default", fontSize: 28,
    color: palette.black, verticalAlign: "top", verticalMetrics: "font",
    maxWidth: screen.width - 48
  });
}
