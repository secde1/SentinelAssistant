"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// Veb faqat trading uchun: bosh sahifa — xodimlar bo'limi.
export default function Home() {
  const router = useRouter();
  useEffect(() => { router.replace("/desk/"); }, [router]);
  return null;
}
