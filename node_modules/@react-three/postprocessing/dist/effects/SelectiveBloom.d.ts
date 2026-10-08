import type { BloomEffectOptions } from 'postprocessing';
import { SelectiveBloomEffect } from 'postprocessing';
import { Ref, RefObject } from 'react';
import { Object3D } from 'three';
type ObjectRef = RefObject<Object3D | null>;
export type SelectiveBloomProps = BloomEffectOptions & Partial<{
    lights: Object3D[] | ObjectRef[];
    selection: Object3D | Object3D[] | ObjectRef | ObjectRef[];
    selectionLayer: number;
    inverted: boolean;
    ignoreBackground: boolean;
    ref?: Ref<SelectiveBloomEffect>;
}>;
export declare function SelectiveBloom({ selection, selectionLayer, lights, luminanceThreshold, luminanceSmoothing, mipmapBlur, radius, levels, resolutionScale, resolutionX, resolutionY, ref, ...liveProps }: SelectiveBloomProps): import("react").JSX.Element;
export {};
