import { DepthDownsamplingPass, EffectComposer as EffectComposerImpl, NormalPass, Pass } from 'postprocessing';
import { type ReactNode, type Ref } from 'react';
import type { Camera, Scene, TextureDataType } from 'three';
export declare const EffectComposerContext: import("react").Context<{
    composer: EffectComposerImpl;
    normalPass: NormalPass | null;
    downSamplingPass: DepthDownsamplingPass | null;
    camera: Camera;
    scene: Scene;
    resolutionScale?: number;
    requestRebuild: () => void;
    autoClear: boolean;
}>;
export type EffectComposerProps = {
    enabled?: boolean;
    children: ReactNode;
    depthBuffer?: boolean;
    /** Only used for SSGI currently, leave it disabled for everything else unless it's needed */
    enableNormalPass?: boolean;
    stencilBuffer?: boolean;
    autoClear?: boolean;
    autoRenderToScreen?: boolean;
    resolutionScale?: number;
    multisampling?: number;
    frameBufferType?: TextureDataType;
    renderPriority?: number;
    camera?: Camera;
    scene?: Scene;
    renderPass?: (scene: Scene, camera: Camera) => Pass;
    mergeMode?: 'auto' | 'all' | 'none';
    ref?: Ref<EffectComposerImpl>;
};
export declare const groupPasses: WeakSet<Pass>;
export declare function disposePassWithoutEffects(pass: Pass): void;
export declare const EffectComposer: import("react").MemoExoticComponent<({ children, camera: _camera, scene: _scene, resolutionScale, enabled, renderPriority, autoClear, autoRenderToScreen, depthBuffer, enableNormalPass, stencilBuffer, multisampling, frameBufferType, renderPass, mergeMode, ref, }: EffectComposerProps) => import("react").JSX.Element | null>;
