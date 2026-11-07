import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-24 text-center">
      <div className="text-5xl font-semibold text-ink-3">404</div>
      <p className="mt-3 text-sm text-ink-2">This page does not exist.</p>
      <Link href="/" className="mt-6 inline-block text-sm text-accent hover:underline">Back to dashboard</Link>
    </div>
  );
}
