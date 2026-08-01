import { cn } from '@/lib/utils';
import logoMark from '../assets/brand/kaigongba-logo-cropped.png';

export type BrandLogoProps = {
  /** Use the compact size in collapsed navigation. */
  markOnly?: boolean;
  /** Requested logo height in pixels. */
  markSize?: number;
  className?: string;
  /** Kept for call-site compatibility; the complete wordmark is part of the image. */
  wordmarkClassName?: string;
};

/** 使用用户提供的完整开工吧 Logo 图片。 */
export default function BrandLogo({
  markOnly = false,
  markSize = 36,
  className,
}: BrandLogoProps) {
  const displayHeight = markOnly ? markSize : Math.max(markSize, 38);

  return (
    <span className={cn('flex items-center overflow-hidden p-[2px]', className)}>
      <img
        src={logoMark}
        alt="开工吧"
        className="shrink-0 object-contain"
        style={{ width: displayHeight * 1.1, height: displayHeight }}
      />
    </span>
  );
}
