document.documentElement.classList.add("js");

const sections = Array.from(document.querySelectorAll(".reveal"));

if ("IntersectionObserver" in window) {
  sections.forEach((section) => section.classList.add("reveal-pending"));

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove("reveal-pending");
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14 }
  );

  sections.forEach((section) => observer.observe(section));
} else {
  sections.forEach((section) => section.classList.add("is-visible"));
}
