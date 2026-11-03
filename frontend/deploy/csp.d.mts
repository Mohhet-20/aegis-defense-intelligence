export declare const TILE_PLACEHOLDER: string
export declare function tileOrigin(tileUrl: string | undefined | null): string
export declare function renderNginx(conf: string, tileUrl: string | undefined | null): string
export declare function cspFromNginx(conf: string): string
export declare function previewCsp(nginxConfPath: string, tileUrl: string | undefined | null): string
