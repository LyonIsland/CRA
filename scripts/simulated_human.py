"""Deterministic human response scheduler. No simulator or robot dependencies.

This models task-level human actions, not hand biomechanics or a learned policy.
Elapsed time advances only while an owner is connected and assistance is allowed.
"""
class SimulatedHuman:
    def __init__(self, enabled=True, response_seconds=2., action_seconds=1.):
        self.enabled=enabled
        self.response_seconds=max(0.,float(response_seconds))
        self.action_seconds=max(0.,float(action_seconds))
        self.reset()

    def reset(self):
        self.request_id=None;self.elapsed=0.;self.phase='idle';self.applied=False

    def advance(self, request_id, dt, allowed):
        if request_id!=self.request_id:
            self.reset();self.request_id=request_id
        if request_id is None or not allowed or not self.enabled:return None
        self.elapsed+=max(0.,min(float(dt),.25))
        if self.phase=='idle':self.phase='responding';return 'announced'
        if self.phase=='responding' and self.elapsed>=self.response_seconds:
            self.phase='acting';return 'action_started'
        if self.phase=='acting' and self.elapsed>=self.response_seconds+self.action_seconds and not self.applied:
            self.applied=True;self.phase='withdrawn';return 'action_completed'
        return None

    def snapshot(self):
        return {'enabled':self.enabled,'phase':self.phase,'request_id':self.request_id,
            'elapsed_active_seconds':round(self.elapsed,3),'response_seconds':self.response_seconds,
            'action_seconds':self.action_seconds,'action_model':'explicit task-level pose edit, no simulated hand contact'}
