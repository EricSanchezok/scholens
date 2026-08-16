import remarkGfm from 'remark-gfm'
import createMDX from '@next/mdx'

/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'standalone' as const,
    // Configure `pageExtensions` to include markdown and MDX files
    pageExtensions: ['js', 'jsx', 'md', 'mdx', 'ts', 'tsx'],
    // Enable source maps in production for error tracking
    productionBrowserSourceMaps: process.env.UPLOAD_SOURCE_MAPS === 'true',
    // Transpile packages that import CSS from node_modules
    transpilePackages: ['react-pdf-highlighter-extended', 'pdfjs-dist'],
}

const withMDX = createMDX({
    // Add markdown plugins here, as desired
    options: {
        remarkPlugins: [remarkGfm],
    }
})

// Merge MDX config with Next.js config
export default withMDX(nextConfig)
