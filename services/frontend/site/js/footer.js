// Shows the version of the release in the footer. The number lives in /version.json and is raised with each release.

try {
  const response = await fetch("/version.json");
  if (response.ok) {
    const { version } = await response.json();
    document.getElementById("version").textContent = `v${version}`;
  }
} catch {
  // the footer then shows only the name
}
