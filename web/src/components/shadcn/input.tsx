import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      // 관리자 검색창·사유 입력에 브라우저가 로그인 이메일을 자동완성해 목록이 비어 보이던
      // 실사용 장애(2026-08-13 실측)의 근본 차단. 필요한 곳은 props 로 덮어쓴다.
      // ⚠️ "off" 로는 안 막힌다 — Chrome 이 검색·이메일류 필드에서 이를 무시하는 것을 실측했다
      // (2026-08-14). 규격에 없는 토큰을 주면 브라우저가 필드 종류를 못 정해 자동완성을 포기한다.
      autoComplete="off-nosuggest"
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-base transition-[color,box-shadow] outline-none selection:bg-primary selection:text-primary-foreground file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
}

export { Input }
