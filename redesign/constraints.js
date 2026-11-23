// Unit-free cycling math. +X is forward, Y is up and Z is the axle.
// Coordinates are in one bike-local frame. The caller creates all visible geometry.
function cyclePose(t, side, crank, radius, halfWidth, hip, thigh, shin, soleHeight) {
  const angle = -Math.PI * t + (side < 0 ? Math.PI : 0);
  const pedal = crank.clone().add(new THREE.Vector3(radius * Math.cos(angle), radius * Math.sin(angle), side * halfWidth));
  const ankle = pedal.clone().add(new THREE.Vector3(0, soleHeight, 0));
  const axis = ankle.clone().sub(hip), d = axis.length();
  axis.normalize();
  const bend = new THREE.Vector3(1, 0, 0);
  bend.addScaledVector(axis, -bend.dot(axis));
  if (bend.lengthSq() < 1e-5) bend.set(0, 1, 0).addScaledVector(axis, -axis.y);
  bend.normalize();
  const reach = Math.max(Math.abs(thigh - shin) + 1e-5, Math.min(thigh + shin - 1e-5, d));
  const along = (thigh * thigh - shin * shin + reach * reach) / (2 * reach);
  const knee = hip.clone().addScaledVector(axis, along).addScaledVector(bend, Math.sqrt(Math.max(0, thigh * thigh - along * along)));
  return {angle, pedal, knee, ankle, reachable: Math.abs(d - reach) < 1e-4};
}
function rollingAngle(distanceTraveled, wheelRadius) { return -distanceTraveled / wheelRadius; }
